"""Production physical vector adapter for partitioned state-law embeddings.

This module consumes the direct-column Parquet parts produced by
``state_laws_embedding_store`` and turns them into the physical vector layout
consumed by the shared remote query engine.  It deliberately keeps each input
part as a bounded clustering unit while assigning globally unique centroid and
shard identifiers across every jurisdiction.

Outputs are:

* jurisdiction-partitioned semantic shards below ``data/vectors``;
* the combined centroid router ``indexes/vector_chunks.parquet``;
* exact-key locator pages below ``indexes/vector_entry_locator``; and
* ``indexes/vector_entry_locator.parquet``, which routes keys to those pages.

Every input part must be covered by a production-ready embedding checkpoint
that proves real sentence-transformers inference in the pinned GTE-small model
space.  Projection/fixture embeddings are rejected.  This writer performs no
network I/O and never authorizes publication.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    NORM_TOLERANCE as EMBEDDING_NORM_TOLERANCE,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    OpenUsLawEmbeddingConfig,
    default_vector_space_id,
    production_inference_evidence_reasons,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    PART_SCHEMA_VERSION as EMBEDDING_PART_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    SCHEMA_VERSION as EMBEDDING_STORE_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    validate_jurisdiction,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    atomic_staging,
    atomic_write_canonical_json,
    confine_path,
    describe_file,
    file_digest,
    resolve_release_root,
    verify_descriptor,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    manifest_descriptor as _descriptor_dict,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    external_sort_to_file,
    file_sha256,
    iter_jsonl,
    stream_bounded_partitions,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_VECTORS,
    LOCATOR_SCHEMA_VERSION,
    LocatorRow,
    validate_locator_ranges,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    ArtifactDescriptor,
    ArtifactFamily,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (
    DEFAULT_KMEANS_ITERATIONS,
    DEFAULT_MAX_CENTROIDS,
    DEFAULT_TARGET_ROWS_PER_CENTROID,
    DEFAULT_TRAINING_ROWS,
    DEFAULT_VECTOR_KMEANS_SEED,
    VECTOR_CHUNK_SCHEMA_VERSION,
    VECTOR_ROUTING_SCHEMA_VERSION,
    compact_centroid_rows_from_routing,
    write_centroid_routed_vectors,
)

SCHEMA_VERSION: Final = "state-laws-vector-physical/v1"
CHECKPOINT_SCHEMA_VERSION: Final = "state-laws-vector-physical-checkpoint/v1"
LOCATOR_PAGE_SCHEMA_VERSION: Final = "state-laws-vector-entry-locator-page/v1"
LOCATOR_META_SCHEMA_VERSION: Final = "state-laws-vector-entry-locator-meta/v1"
CENTROID_SCHEMA_VERSION: Final = "state-laws-vector-centroid/v1"

VECTOR_DATA_DIR: Final = "data/vectors"
CENTROID_DATA_PATH: Final = "data/vectors/centroids/part-000000.parquet"
VECTOR_INDEX_PATH: Final = "indexes/vector_chunks.parquet"
ENTRY_LOCATOR_DIR: Final = "indexes/vector_entry_locator"
ENTRY_LOCATOR_INDEX_PATH: Final = "indexes/vector_entry_locator.parquet"
DEFAULT_CHECKPOINT_PATH: Final = "checkpoints/vector_physical.json"
DEFAULT_SORT_WORK_DIR: Final = "checkpoints/vector_locator_sort"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PROJECTION_EMBEDDINGS_ALLOWED: Final = False
LEGACY_VECTOR_WRITER_PRODUCTION_READY: Final = False
STREAMING_VECTOR_PHYSICAL_PRODUCTION_READY: Final = True

_PART_RE: Final = re.compile(r"^part-(\d{6})\.parquet$")
_JURISDICTION_RE: Final = re.compile(r"^jurisdiction=([A-Z]{2})$")
_HEX_64_RE: Final = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_INPUT_COLUMNS: Final = frozenset(
    {
        "chunk_cid",
        "chunk_id",
        "config_cid",
        "dimension",
        "document_index",
        "embedding",
        "entry_cid",
        "input_hash",
        "jurisdiction_code",
        "model_id",
        "model_revision",
        "normalization",
        "parent_entry_cid",
        "pooling",
        "schema_version",
        "vector_space_id",
    }
)


class StateLawsVectorPhysicalError(ValueError):
    """Raised when a production vector layout cannot close safely."""


class StateLawsVectorInputDriftError(StateLawsVectorPhysicalError):
    """Raised when an input/checkpoint no longer matches its recorded digest."""


class StateLawsVectorOutputDriftError(StateLawsVectorPhysicalError):
    """Raised when a completed physical artifact fails descriptor integrity."""


class ProjectionEmbeddingRejectedError(StateLawsVectorPhysicalError):
    """Raised when source evidence does not prove real pinned inference."""


@dataclass(frozen=True, slots=True)
class _InputPart:
    path: Path
    source_root: Path
    source_checkpoint_path: Path
    source_checkpoint_sha256: str
    source_checkpoint_part_count: int
    source_checkpoint_row_count: int
    source_id: str
    jurisdiction_code: str
    part_index: int
    row_count: int
    sha256: str
    size_bytes: int
    source_input_digest: str
    config_digest: str
    config_cid: str
    vector_space_id: str
    first_document_index: int
    last_document_index: int
    parent_entry_cids: tuple[str, ...]

    @property
    def input_digest(self) -> str:
        return content_sha256(
            canonical_json_dumps(
                {
                    "config_cid": self.config_cid,
                    "config_digest": self.config_digest,
                    "jurisdiction_code": self.jurisdiction_code,
                    "part_index": self.part_index,
                    "row_count": self.row_count,
                    "sha256": self.sha256,
                    "size_bytes": self.size_bytes,
                    "source_checkpoint_sha256": self.source_checkpoint_sha256,
                    "source_checkpoint_part_count": self.source_checkpoint_part_count,
                    "source_checkpoint_row_count": self.source_checkpoint_row_count,
                    "source_id": self.source_id,
                    "source_input_digest": self.source_input_digest,
                    "vector_space_id": self.vector_space_id,
                }
            )
        )

    def inventory_row(self) -> dict[str, Any]:
        return {
            "config_cid": self.config_cid,
            "config_digest": self.config_digest,
            "first_document_index": self.first_document_index,
            "input_digest": self.input_digest,
            "jurisdiction_code": self.jurisdiction_code,
            "last_document_index": self.last_document_index,
            "part_index": self.part_index,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_checkpoint_sha256": self.source_checkpoint_sha256,
            "source_checkpoint_part_count": self.source_checkpoint_part_count,
            "source_checkpoint_row_count": self.source_checkpoint_row_count,
            "source_id": self.source_id,
            "source_input_digest": self.source_input_digest,
            "vector_space_id": self.vector_space_id,
        }


@dataclass(frozen=True, slots=True)
class StateLawsVectorPhysicalResult:
    """Descriptor-complete result for one production physical vector build."""

    output_root: str
    checkpoint_path: str
    build_digest: str
    row_count: int
    jurisdiction_count: int
    input_part_count: int
    resumed_part_count: int
    executed_part_count: int
    cluster_count: int
    shard_count: int
    vector_data_descriptors: tuple[Mapping[str, Any], ...]
    centroid_descriptor: Mapping[str, Any]
    vector_index_descriptor: Mapping[str, Any]
    locator_page_descriptors: tuple[Mapping[str, Any], ...]
    locator_index_descriptor: Mapping[str, Any]
    routing_rows: tuple[Mapping[str, Any], ...]
    config: Mapping[str, Any]
    model: Mapping[str, Any]
    sort_receipt: Mapping[str, Any]
    parent_entry_cids: tuple[str, ...]
    production_ready: bool = True
    schema_version: str = SCHEMA_VERSION

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {
            "vector_chunks": dict(self.vector_index_descriptor),
            "vector_entry_locator": dict(self.locator_index_descriptor),
        }

    @property
    def artifacts(self) -> tuple[Mapping[str, Any], ...]:
        """Vector, centroid, and exact-locator data descriptors."""

        return (
            *self.vector_data_descriptors,
            dict(self.centroid_descriptor),
            *self.locator_page_descriptors,
        )

    @property
    def key_evidence(self) -> dict[str, tuple[str, ...]]:
        """Runtime-only parent identities used for cross-stage closure."""

        return {"parent_entry_cids": self.parent_entry_cids}

    def iter_chunk_cids(self) -> Iterator[str]:
        """Replay exact vector chunk keys from verified locator pages.

        Duplicates are deliberately not collapsed; production validation and
        downstream parity gates must be able to observe and reject them.
        """

        root = Path(self.output_root)
        for page_index, value in enumerate(self.locator_page_descriptors):
            descriptor = _verify_output_descriptor(
                root, value, label=f"vector locator page {page_index}"
            )
            if (
                descriptor.family is not ArtifactFamily.LOCATOR_INDEX
                or descriptor.schema_id != LOCATOR_PAGE_SCHEMA_VERSION
                or descriptor.relative_path
                != f"{ENTRY_LOCATOR_DIR}/part-{page_index:06d}.parquet"
            ):
                raise StateLawsVectorOutputDriftError(
                    f"vector locator page contract drift at {page_index}"
                )
            path = confine_path(root, descriptor.relative_path)
            table = _parquet().read_table(path, columns=["entry_cid"])
            if table.num_rows != descriptor.row_count:
                raise StateLawsVectorOutputDriftError(
                    f"vector locator page row drift at {page_index}"
                )
            for value in table.column("entry_cid").to_pylist():
                key = str(value or "")
                if not key:
                    raise StateLawsVectorOutputDriftError(
                        f"empty vector chunk key at locator page {page_index}"
                    )
                yield key

    def iter_document_chunk_keys(self) -> Iterator[tuple[int, str]]:
        """Replay the vector document-index/chunk mapping from exact locators."""

        root = Path(self.output_root)
        observed = 0
        for page_index, value in enumerate(self.locator_page_descriptors):
            descriptor = _verify_output_descriptor(
                root, value, label=f"vector locator page {page_index}"
            )
            path = confine_path(root, descriptor.relative_path)
            table = _parquet().read_table(
                path,
                columns=["document_index", "entry_cid"],
            )
            if table.num_rows != descriptor.row_count:
                raise StateLawsVectorOutputDriftError(
                    f"vector locator page row drift at {page_index}"
                )
            for row in table.to_pylist():
                document_index = int(row.get("document_index", -1))
                chunk_cid = str(row.get("entry_cid") or "")
                if document_index < 0 or not chunk_cid:
                    raise StateLawsVectorOutputDriftError(
                        f"invalid vector positional key at locator page {page_index}"
                    )
                observed += 1
                yield document_index, chunk_cid
        if observed != self.row_count:
            raise StateLawsVectorOutputDriftError(
                "vector positional key evidence does not conserve rows"
            )

    @property
    def descriptors(self) -> tuple[Mapping[str, Any], ...]:
        return (
            *self.vector_data_descriptors,
            dict(self.centroid_descriptor),
            dict(self.vector_index_descriptor),
            *self.locator_page_descriptors,
            dict(self.locator_index_descriptor),
        )

    @property
    def counts(self) -> dict[str, int]:
        return {
            "vector_centroids": self.cluster_count,
            "vector_entry_locator_pages": len(self.locator_page_descriptors),
            "vector_rows": self.row_count,
            "vector_shards": self.shard_count,
        }

    def to_manifest_fragment(self) -> dict[str, Any]:
        vector = {
            **dict(self.config),
            **dict(self.model),
            "centroid_count": self.cluster_count,
            "default_probe_centroids": min(
                DEFAULT_CANDIDATE_CENTROIDS, self.cluster_count
            ),
            "layout": "semantic_centroid_groups",
            "inference": {
                "embedder_kind": "sentence_transformers",
                "real_inference": True,
            },
            "projection_embeddings": False,
            "production_ready": True,
            "max_rows_per_chunk": self.config["max_rows_per_shard"],
            "shard_count": self.shard_count,
            "total_rows": self.row_count,
        }
        return {
            "artifacts": [dict(item) for item in self.artifacts],
            "configs": {
                "centroids": CENTROID_DATA_PATH,
                "vector_entry_locator": ENTRY_LOCATOR_INDEX_PATH,
                "vectors": (
                    f"{VECTOR_DATA_DIR}/jurisdiction=*/source_part=*/*.parquet"
                ),
            },
            "counts": self.counts,
            "inference": dict(vector["inference"]),
            "indexes": self.indexes,
            "key_evidence": self.key_evidence,
            "production_ready": True,
            "vector": vector,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_digest": self.build_digest,
            "checkpoint_path": self.checkpoint_path,
            "cluster_count": self.cluster_count,
            "config": dict(self.config),
            "descriptors": [dict(item) for item in self.descriptors],
            "executed_part_count": self.executed_part_count,
            "indexes": self.indexes,
            "input_part_count": self.input_part_count,
            "jurisdiction_count": self.jurisdiction_count,
            "model": dict(self.model),
            "output_root": self.output_root,
            "production_ready": self.production_ready,
            "resumed_part_count": self.resumed_part_count,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "shard_count": self.shard_count,
            "sort_receipt": dict(self.sort_receipt),
        }


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise StateLawsVectorPhysicalError(f"{label} must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsVectorPhysicalError(f"invalid {label}: {path}") from exc
    if not isinstance(payload, Mapping):
        raise StateLawsVectorPhysicalError(f"{label} must be a JSON object")
    return dict(payload)


def _redescribe(root: Path, descriptor: ArtifactDescriptor) -> ArtifactDescriptor:
    return describe_file(
        confine_path(root, descriptor.relative_path),
        root=root,
        row_count=descriptor.row_count,
        family=descriptor.family,
        schema_id=descriptor.schema_id,
        first_key=descriptor.first_key,
        last_key=descriptor.last_key,
        shard_id=descriptor.shard_id,
        metadata=dict(descriptor.metadata),
    )


def _verify_output_descriptor(
    root: Path, value: Mapping[str, Any], *, label: str
) -> ArtifactDescriptor:
    try:
        descriptor = ArtifactDescriptor.from_mapping(value)
        verify_descriptor(root, descriptor)
    except Exception as exc:
        raise StateLawsVectorOutputDriftError(
            f"{label} descriptor drift: {value.get('relative_path')!r}"
        ) from exc
    return descriptor


def _source_checkpoint_for_part(path: Path, jurisdiction: str) -> tuple[Path, Path]:
    if path.parent.parent.name != "embeddings":
        raise StateLawsVectorPhysicalError(
            "embedding parts must use <root>/embeddings/jurisdiction=XX/part-*.parquet"
        )
    source_root = path.parents[2]
    checkpoint = source_root / "checkpoints" / "embeddings" / f"{jurisdiction}.json"
    return source_root, checkpoint


def _assert_production_checkpoint(
    checkpoint: Mapping[str, Any], *, jurisdiction: str
) -> OpenUsLawEmbeddingConfig:
    inference = checkpoint.get("inference")
    evidence_reasons = production_inference_evidence_reasons(inference)
    try:
        source_config = OpenUsLawEmbeddingConfig.from_mapping(checkpoint["config"])
    except Exception as exc:
        raise ProjectionEmbeddingRejectedError(
            f"{jurisdiction} embedding checkpoint config is missing or invalid"
        ) from exc
    sort_receipt = checkpoint.get("sort_receipt")
    row_count = checkpoint.get("row_count")
    receipt_invalid = (
        not isinstance(sort_receipt, Mapping)
        or sort_receipt.get("family") != "chunks"
        or sort_receipt.get("status") != "complete"
        or sort_receipt.get("interrupted") is not False
        or type(row_count) is not int
        or row_count < 1
        or int(sort_receipt.get("row_count") or -1) != row_count
        or int(sort_receipt.get("records_consumed") or -1) != row_count
        or type(sort_receipt.get("max_records_in_memory")) is not int
        or int(sort_receipt.get("max_records_in_memory") or 0) < 2
        or type(sort_receipt.get("peak_resident_records")) is not int
        or int(sort_receipt.get("peak_resident_records") or -1) < 1
        or int(sort_receipt.get("peak_resident_records") or -1)
        > int(sort_receipt.get("max_records_in_memory") or 0)
        or _HEX_64_RE.fullmatch(str(sort_receipt.get("output_digest") or "")) is None
    )
    if (
        checkpoint.get("schema_version") != EMBEDDING_STORE_SCHEMA_VERSION
        or checkpoint.get("jurisdiction_code") != jurisdiction
        or checkpoint.get("production_ready") is not True
        or checkpoint.get("config_digest") != source_config.digest
        or not source_config.may_authorize_release
        or evidence_reasons
        or receipt_invalid
    ):
        raise ProjectionEmbeddingRejectedError(
            f"{jurisdiction} embedding checkpoint does not prove production "
            f"sentence-transformers inference: {list(evidence_reasons)}"
        )
    return source_config


def _parquet() -> Any:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise StateLawsVectorPhysicalError(
            "pyarrow is required for the state-law vector physical adapter"
        ) from exc
    return pq


def _prepare_input_part(path_value: str | Path) -> _InputPart:
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise StateLawsVectorPhysicalError(
            f"embedding part must be a regular file: {path}"
        )
    path = path.resolve()
    part_match = _PART_RE.fullmatch(path.name)
    jurisdiction_match = _JURISDICTION_RE.fullmatch(path.parent.name)
    if part_match is None or jurisdiction_match is None:
        raise StateLawsVectorPhysicalError(
            f"embedding part path is not canonical: {path}"
        )
    part_index = int(part_match.group(1))
    jurisdiction = validate_jurisdiction(
        jurisdiction_match.group(1), name="jurisdiction_code"
    )
    source_root, checkpoint_path = _source_checkpoint_for_part(path, jurisdiction)
    checkpoint = _load_json(checkpoint_path, label="embedding checkpoint")
    source_config = _assert_production_checkpoint(checkpoint, jurisdiction=jurisdiction)
    config_digest = str(checkpoint.get("config_digest") or "")
    if _HEX_64_RE.fullmatch(config_digest) is None:
        raise StateLawsVectorPhysicalError(
            f"{jurisdiction} embedding checkpoint config_digest is invalid"
        )
    part_values = checkpoint.get("parts")
    if not isinstance(part_values, Sequence) or isinstance(
        part_values, (str, bytes, bytearray)
    ):
        raise StateLawsVectorInputDriftError(
            f"embedding checkpoint parts are malformed for {jurisdiction}"
        )
    all_parts: dict[int, dict[str, Any]] = {}
    for item in part_values:
        if not isinstance(item, Mapping) or type(item.get("part_index")) is not int:
            raise StateLawsVectorInputDriftError(
                f"embedding checkpoint part record is malformed for {jurisdiction}"
            )
        index = int(item["part_index"])
        if index < 0 or index in all_parts:
            raise StateLawsVectorInputDriftError(
                f"embedding checkpoint part indexes differ for {jurisdiction}"
            )
        all_parts[index] = dict(item)
    checkpoint_row_count = int(checkpoint["row_count"])
    if (
        sorted(all_parts) != list(range(len(all_parts)))
        or sum(int(item.get("row_count") or 0) for item in all_parts.values())
        != checkpoint_row_count
    ):
        raise StateLawsVectorInputDriftError(
            f"embedding checkpoint part coverage differs for {jurisdiction}"
        )
    prior = all_parts.get(part_index)
    if prior is None or not isinstance(prior.get("descriptor"), Mapping):
        raise StateLawsVectorInputDriftError(
            f"embedding checkpoint does not cover {jurisdiction} part {part_index}"
        )
    descriptor = ArtifactDescriptor.from_mapping(prior["descriptor"])
    expected_source_path = (
        f"embeddings/jurisdiction={jurisdiction}/part-{part_index:06d}.parquet"
    )
    if (
        descriptor.relative_path != expected_source_path
        or descriptor.family is not ArtifactFamily.VECTORS
        or descriptor.schema_id != EMBEDDING_PART_SCHEMA_VERSION
        or descriptor.shard_id != part_index
        or descriptor.metadata.get("jurisdiction_code") != jurisdiction
        or descriptor.metadata.get("stage") != "embedding_store"
        or prior.get("sha256") != descriptor.sha256
    ):
        raise StateLawsVectorInputDriftError(
            f"source descriptor contract drift for {jurisdiction} part {part_index}"
        )
    try:
        verified = verify_descriptor(source_root, descriptor)
    except Exception as exc:
        raise StateLawsVectorInputDriftError(
            f"source descriptor drift for {jurisdiction} part {part_index}"
        ) from exc
    if verified != path:
        raise StateLawsVectorInputDriftError(
            f"source descriptor points at a different file for {jurisdiction} "
            f"part {part_index}"
        )
    source_input_digest = str(prior.get("input_digest") or "")
    if _HEX_64_RE.fullmatch(source_input_digest) is None:
        raise StateLawsVectorInputDriftError(
            f"source input digest is invalid for {jurisdiction} part {part_index}"
        )
    inference_digest = content_sha256(canonical_json_dumps(checkpoint["inference"]))
    if prior.get("inference_digest") != inference_digest:
        raise StateLawsVectorInputDriftError(
            f"source inference evidence is unbound for {jurisdiction} part {part_index}"
        )

    pq = _parquet()
    parquet = pq.ParquetFile(path)
    row_count = int(parquet.metadata.num_rows)
    columns = set(parquet.schema_arrow.names)
    missing = _REQUIRED_INPUT_COLUMNS.difference(columns)
    if missing:
        raise StateLawsVectorPhysicalError(
            f"embedding part lacks direct columns {sorted(missing)}: {path}"
        )
    if "record_json" in columns:
        raise StateLawsVectorPhysicalError(
            f"record_json wrappers are forbidden in embedding parts: {path}"
        )
    if not 1 <= row_count <= MAX_ROWS_PER_PHYSICAL_SHARD:
        raise StateLawsVectorPhysicalError(
            f"embedding part row_count must be 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if row_count != descriptor.row_count:
        raise StateLawsVectorInputDriftError(
            f"source row_count drift for {jurisdiction} part {part_index}"
        )

    metadata_columns = sorted(_REQUIRED_INPUT_COLUMNS.difference({"embedding"}))
    rows = pq.read_table(path, columns=metadata_columns).to_pylist()
    keys: set[str] = set()
    ordered_keys: list[str] = []
    document_indexes: list[int] = []
    config_cids: set[str] = set()
    vector_spaces: set[str] = set()
    parent_entry_cids: list[str] = []
    for row in rows:
        entry_cid = str(row.get("entry_cid") or "")
        chunk_cid = str(row.get("chunk_cid") or "")
        if not entry_cid or entry_cid != chunk_cid or entry_cid in keys:
            raise StateLawsVectorPhysicalError(
                f"embedding keys are missing, duplicated, or unbound in {path}"
            )
        keys.add(entry_cid)
        ordered_keys.append(entry_cid)
        if (
            row.get("schema_version") != EMBEDDING_PART_SCHEMA_VERSION
            or row.get("jurisdiction_code") != jurisdiction
            or row.get("model_id") != PINNED_MODEL_ID
            or row.get("model_revision") != PINNED_MODEL_REVISION
            or int(row.get("dimension") or 0) != PINNED_DIMENSION
            or row.get("pooling") != PINNED_POOLING
            or row.get("normalization") != PINNED_NORMALIZATION
            or _HEX_64_RE.fullmatch(str(row.get("input_hash") or "")) is None
        ):
            raise ProjectionEmbeddingRejectedError(
                f"embedding row is outside the pinned GTE-small space: {entry_cid}"
            )
        document_index = int(row.get("document_index", -1))
        if document_index < 0:
            raise StateLawsVectorPhysicalError(
                f"negative source document_index for {entry_cid}"
            )
        document_indexes.append(document_index)
        parent_entry_cid = str(row.get("parent_entry_cid") or "")
        if not parent_entry_cid:
            raise StateLawsVectorPhysicalError(
                f"empty parent_entry_cid for {entry_cid}"
            )
        parent_entry_cids.append(parent_entry_cid)
        config_cids.add(str(row.get("config_cid") or ""))
        vector_spaces.add(str(row.get("vector_space_id") or ""))
    expected_document_start = int(prior.get("document_index_start", -1))
    if document_indexes != list(
        range(expected_document_start, expected_document_start + row_count)
    ):
        raise StateLawsVectorPhysicalError(
            f"source document indexes are not dense/ordered in {path}"
        )
    if config_cids != {source_config.config_cid}:
        raise StateLawsVectorPhysicalError(f"embedding config_cid drift in {path}")
    if vector_spaces != {default_vector_space_id()}:
        raise ProjectionEmbeddingRejectedError(
            f"embedding vector_space_id differs from the pinned GTE-small space: {path}"
        )
    if (
        descriptor.first_key != ordered_keys[0]
        or descriptor.last_key != ordered_keys[-1]
    ):
        raise StateLawsVectorInputDriftError(
            f"embedding descriptor key bounds differ for {jurisdiction} part {part_index}"
        )

    return _InputPart(
        path=path,
        source_root=source_root,
        source_checkpoint_path=checkpoint_path,
        source_checkpoint_sha256=file_digest(checkpoint_path)[1].hex(),
        source_checkpoint_part_count=len(all_parts),
        source_checkpoint_row_count=checkpoint_row_count,
        source_id=f"jurisdiction={jurisdiction}/part-{part_index:06d}",
        jurisdiction_code=jurisdiction,
        part_index=part_index,
        row_count=row_count,
        sha256=descriptor.sha256,
        size_bytes=descriptor.size_bytes,
        source_input_digest=source_input_digest,
        config_digest=config_digest,
        config_cid=next(iter(config_cids)),
        vector_space_id=next(iter(vector_spaces)),
        first_document_index=document_indexes[0],
        last_document_index=document_indexes[-1],
        parent_entry_cids=tuple(parent_entry_cids),
    )


def _prepare_inputs(values: Iterable[str | Path]) -> tuple[_InputPart, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise StateLawsVectorPhysicalError(
            "input_parts must be a non-empty iterable of Parquet paths"
        )
    prepared: list[_InputPart] = []
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise StateLawsVectorPhysicalError(
            "input_parts must be a non-empty iterable of Parquet paths"
        ) from exc
    for value in iterator:
        prepared.append(_prepare_input_part(value))
        if len(prepared) > MAX_ROUTING_ROWS_PER_INDEX:
            raise StateLawsVectorPhysicalError(
                "input part count exceeds the bounded routing limit"
            )
    if not prepared:
        raise StateLawsVectorPhysicalError(
            "input_parts must be a non-empty iterable of Parquet paths"
        )
    parts = sorted(
        prepared,
        key=lambda item: (item.jurisdiction_code, item.part_index, item.source_id),
    )
    source_ids = [item.source_id for item in parts]
    if len(source_ids) != len(set(source_ids)):
        raise StateLawsVectorPhysicalError("duplicate jurisdiction/part input")
    if len({item.config_digest for item in parts}) != 1:
        raise StateLawsVectorPhysicalError(
            "embedding config_digest differs across parts"
        )
    if len({item.config_cid for item in parts}) != 1:
        raise StateLawsVectorPhysicalError("embedding config_cid differs across parts")
    if len({item.vector_space_id for item in parts}) != 1:
        raise StateLawsVectorPhysicalError(
            "embedding vector_space_id differs across parts"
        )
    by_jurisdiction: dict[str, list[_InputPart]] = {}
    for part in parts:
        by_jurisdiction.setdefault(part.jurisdiction_code, []).append(part)
    for jurisdiction, jurisdiction_parts in by_jurisdiction.items():
        expected_part_count = {
            part.source_checkpoint_part_count for part in jurisdiction_parts
        }
        expected_row_count = {
            part.source_checkpoint_row_count for part in jurisdiction_parts
        }
        if (
            len(expected_part_count) != 1
            or len(expected_row_count) != 1
            or [part.part_index for part in jurisdiction_parts]
            != list(range(next(iter(expected_part_count))))
            or sum(part.row_count for part in jurisdiction_parts)
            != next(iter(expected_row_count))
        ):
            raise StateLawsVectorInputDriftError(
                f"input parts do not close the full {jurisdiction} embedding checkpoint"
            )
        previous_last: int | None = None
        for part in jurisdiction_parts:
            if previous_last is not None and part.first_document_index <= previous_last:
                raise StateLawsVectorPhysicalError(
                    f"source document indexes overlap across {jurisdiction} parts"
                )
            previous_last = part.last_document_index
    return tuple(parts)


def _load_vector_rows(
    part: _InputPart, *, global_document_offset: int
) -> tuple[dict[str, Any], ...]:
    pq = _parquet()
    rows = pq.read_table(part.path).to_pylist()
    output: list[dict[str, Any]] = []
    for offset, row in enumerate(rows):
        embedding = row.get("embedding")
        if not isinstance(embedding, Sequence) or isinstance(
            embedding, (str, bytes, bytearray)
        ):
            raise StateLawsVectorPhysicalError(
                f"embedding must be a numeric sequence: {row.get('entry_cid')!r}"
            )
        vector = tuple(float(value) for value in embedding)
        if len(vector) != PINNED_DIMENSION or any(
            not math.isfinite(value) for value in vector
        ):
            raise ProjectionEmbeddingRejectedError(
                f"embedding dimension/values differ for {row.get('entry_cid')!r}"
            )
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isclose(norm, 1.0, abs_tol=EMBEDDING_NORM_TOLERANCE, rel_tol=0.0):
            raise ProjectionEmbeddingRejectedError(
                f"embedding is not L2-normalized: {row.get('entry_cid')!r}"
            )
        output.append(
            {
                "document_index": global_document_offset + offset,
                "embedding": list(vector),
                "entry_cid": str(row["entry_cid"]),
            }
        )
    return tuple(output)


def _build_config(
    *,
    seed: int,
    max_rows_per_shard: int,
    max_shards_per_centroid: int,
    max_rows_per_centroid: int,
    target_rows_per_centroid: int,
    max_centroids: int,
    kmeans_iterations: int,
    max_training_rows: int,
    locator_page_size: int,
    max_sort_records_in_memory: int,
) -> dict[str, Any]:
    return {
        "assignment": "deterministic_balanced_spherical_kmeans",
        "kmeans_iterations": kmeans_iterations,
        "locator_page_size": locator_page_size,
        "max_centroids_per_input_part": max_centroids,
        "max_rows_per_centroid": max_rows_per_centroid,
        "max_rows_per_shard": max_rows_per_shard,
        "max_shards_per_centroid": max_shards_per_centroid,
        "max_sort_records_in_memory": max_sort_records_in_memory,
        "max_training_rows_per_input_part": max_training_rows,
        "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
        "seed": seed,
        "similarity": "cosine",
        "source_partition_policy": "jurisdiction_then_embedding_part",
        "target_rows_per_centroid": target_rows_per_centroid,
    }


def _model_manifest(part: _InputPart) -> dict[str, Any]:
    return {
        "config_cid": part.config_cid,
        "dimension": PINNED_DIMENSION,
        "model_id": PINNED_MODEL_ID,
        "model_name": PINNED_MODEL_ID,
        "model_revision": PINNED_MODEL_REVISION,
        "normalization": PINNED_NORMALIZATION,
        "pooling": PINNED_POOLING,
        "source_embedding_schema": EMBEDDING_PART_SCHEMA_VERSION,
        "source_production_ready": True,
        "vector_space_id": part.vector_space_id,
    }


def _build_digest(parts: Sequence[_InputPart], config: Mapping[str, Any]) -> str:
    return content_sha256(
        canonical_json_dumps(
            {
                "config": dict(config),
                "inputs": [part.inventory_row() for part in parts],
                "model": _model_manifest(parts[0]),
                "schema_version": SCHEMA_VERSION,
            }
        )
    )


def _load_physical_checkpoint(path: Path, *, resume: bool) -> dict[str, Any]:
    if not resume or not path.exists():
        return {}
    if path.is_symlink():
        raise StateLawsVectorPhysicalError("vector checkpoint must not be a symlink")
    return _load_json(path, label="vector physical checkpoint")


def _checkpoint_payload(
    *,
    build_digest: str,
    config: Mapping[str, Any],
    model: Mapping[str, Any],
    inputs: Sequence[_InputPart],
    completed_parts: Sequence[Mapping[str, Any]],
    status: str,
    final: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "build_digest": build_digest,
        "completed_parts": [dict(item) for item in completed_parts],
        "config": dict(config),
        "inputs": [part.inventory_row() for part in inputs],
        "model": dict(model),
        "row_count": sum(part.row_count for part in inputs),
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "status": status,
    }
    if final is not None:
        payload["final"] = dict(final)
    return payload


def _validate_checkpoint_identity(
    checkpoint: Mapping[str, Any],
    *,
    build_digest: str,
    config: Mapping[str, Any],
    model: Mapping[str, Any],
    inputs: Sequence[_InputPart],
) -> None:
    expected_inputs = [part.inventory_row() for part in inputs]
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("build_digest") != build_digest
        or checkpoint.get("status") not in {"building", "complete"}
        or canonical_json_dumps(checkpoint.get("config"))
        != canonical_json_dumps(dict(config))
        or canonical_json_dumps(checkpoint.get("model"))
        != canonical_json_dumps(dict(model))
        or canonical_json_dumps(checkpoint.get("inputs"))
        != canonical_json_dumps(expected_inputs)
        or int(checkpoint.get("row_count") or -1)
        != sum(part.row_count for part in inputs)
    ):
        raise StateLawsVectorInputDriftError(
            "vector physical checkpoint does not match active inputs/config"
        )


def _expected_data_dir(part: _InputPart) -> str:
    return (
        f"{VECTOR_DATA_DIR}/jurisdiction={part.jurisdiction_code}/"
        f"source_part={part.part_index:06d}"
    )


def _validate_part_record(
    record: Mapping[str, Any],
    *,
    part: _InputPart,
    root: Path,
    cluster_offset: int,
    shard_offset: int,
    document_offset: int,
) -> None:
    if (
        record.get("source_id") != part.source_id
        or record.get("input_digest") != part.input_digest
        or int(record.get("cluster_id_offset", -1)) != cluster_offset
        or int(record.get("global_shard_id_offset", -1)) != shard_offset
        or int(record.get("global_document_index_offset", -1)) != document_offset
        or int(record.get("row_count", -1)) != part.row_count
    ):
        raise StateLawsVectorInputDriftError(
            f"resumable vector record differs for {part.source_id}"
        )
    descriptors = [
        dict(item)
        for item in record.get("data_descriptors", [])
        if isinstance(item, Mapping)
    ]
    routes = [
        dict(item)
        for item in record.get("routing_rows", [])
        if isinstance(item, Mapping)
    ]
    cluster_count = int(record.get("cluster_count", 0))
    shard_count = int(record.get("shard_count", 0))
    if len(descriptors) != shard_count or len(routes) != shard_count:
        raise StateLawsVectorOutputDriftError(
            f"vector descriptor/route count differs for {part.source_id}"
        )
    cluster_ids = sorted({int(row["cluster_id"]) for row in routes})
    shard_ids = sorted(int(row["shard_id"]) for row in routes)
    if cluster_ids != list(range(cluster_offset, cluster_offset + cluster_count)):
        raise StateLawsVectorOutputDriftError(
            f"cluster offsets are not dense for {part.source_id}"
        )
    if shard_ids != list(range(shard_offset, shard_offset + shard_count)):
        raise StateLawsVectorOutputDriftError(
            f"shard offsets are not dense for {part.source_id}"
        )
    try:
        compact_centroid_rows_from_routing(
            routes,
            assignment="resume_validation",
            schema_version=CENTROID_SCHEMA_VERSION,
            context_fields=("jurisdiction_code", "source_part_index"),
        )
    except Exception as exc:
        raise StateLawsVectorOutputDriftError(
            f"centroid route contract differs for {part.source_id}"
        ) from exc
    descriptor_by_path: dict[str, ArtifactDescriptor] = {}
    expected_prefix = f"{_expected_data_dir(part)}/"
    for value in descriptors:
        descriptor = _verify_output_descriptor(
            root, value, label=f"{part.source_id} vector data"
        )
        if (
            not descriptor.relative_path.startswith(expected_prefix)
            or descriptor.family is not ArtifactFamily.VECTORS
            or descriptor.schema_id != VECTOR_CHUNK_SCHEMA_VERSION
        ):
            raise StateLawsVectorOutputDriftError(
                f"vector path escaped its jurisdiction partition: "
                f"{descriptor.relative_path}"
            )
        path = confine_path(root, descriptor.relative_path)
        parquet = _parquet().ParquetFile(path)
        names = set(parquet.schema_arrow.names)
        if "record_json" in names or not {
            "chunk_in_cluster",
            "cluster_id",
            "document_index",
            "embedding",
            "entry_cid",
            "schema_version",
        }.issubset(names):
            raise StateLawsVectorOutputDriftError(
                f"vector shard is not direct-column Parquet: {descriptor.relative_path}"
            )
        descriptor_by_path[descriptor.relative_path] = descriptor
    if set(descriptor_by_path) != {
        str(row.get("relative_path") or "") for row in routes
    }:
        raise StateLawsVectorOutputDriftError(
            f"vector routes/descriptors disagree for {part.source_id}"
        )
    row_count = 0
    document_indexes: list[int] = []
    entry_cids: set[str] = set()
    for route in routes:
        descriptor = descriptor_by_path[str(route["relative_path"])]
        if (
            route.get("sha256") != descriptor.sha256
            or int(route.get("size_bytes") or -1) != descriptor.size_bytes
            or int(route.get("row_count") or -1) != descriptor.row_count
            or descriptor.shard_id != int(route["shard_id"])
            or route.get("jurisdiction_code") != part.jurisdiction_code
            or int(route.get("source_part_index", -1)) != part.part_index
            or route.get("source_input_digest") != part.input_digest
        ):
            raise StateLawsVectorOutputDriftError(
                f"routing descriptor drift for {descriptor.relative_path}"
            )
        path = confine_path(root, descriptor.relative_path)
        shard_rows = (
            _parquet()
            .read_table(
                path,
                columns=[
                    "chunk_in_cluster",
                    "cluster_id",
                    "document_index",
                    "entry_cid",
                    "schema_version",
                ],
            )
            .to_pylist()
        )
        keys = [str(row.get("entry_cid") or "") for row in shard_rows]
        if (
            len(shard_rows) != descriptor.row_count
            or not keys
            or descriptor.first_key != keys[0]
            or descriptor.last_key != keys[-1]
            or any(not key for key in keys)
            or len(keys) != len(set(keys))
            or bool(entry_cids.intersection(keys))
            or any(
                int(row.get("cluster_id", -1)) != int(route["cluster_id"])
                or int(row.get("chunk_in_cluster", -1))
                != int(route["chunk_in_cluster"])
                or row.get("schema_version") != VECTOR_CHUNK_SCHEMA_VERSION
                for row in shard_rows
            )
        ):
            raise StateLawsVectorOutputDriftError(
                f"vector shard rows disagree for {descriptor.relative_path}"
            )
        entry_cids.update(keys)
        document_indexes.extend(int(row["document_index"]) for row in shard_rows)
        row_count += descriptor.row_count
    if row_count != part.row_count or sorted(document_indexes) != list(
        range(document_offset, document_offset + part.row_count)
    ):
        raise StateLawsVectorOutputDriftError(
            f"vector row/document coverage drift for {part.source_id}"
        )


def _write_part(
    part: _InputPart,
    *,
    root: Path,
    ordinal: int,
    cluster_offset: int,
    shard_offset: int,
    document_offset: int,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _load_vector_rows(part, global_document_offset=document_offset)
    data_dir = _expected_data_dir(part)
    destination = confine_path(root, data_dir)
    if destination.is_symlink():
        raise StateLawsVectorPhysicalError(
            f"refusing to replace symlinked vector partition: {data_dir}"
        )
    with atomic_staging(root, prefix=".state-laws-vector-part-") as session:
        written = write_centroid_routed_vectors(
            rows,
            session.staging_dir,
            seed=int(config["seed"]) + ordinal,
            cluster_id_offset=cluster_offset,
            global_shard_id_offset=shard_offset,
            max_rows_per_shard=int(config["max_rows_per_shard"]),
            max_shards_per_centroid=int(config["max_shards_per_centroid"]),
            max_rows_per_centroid=int(config["max_rows_per_centroid"]),
            target_rows_per_centroid=int(config["target_rows_per_centroid"]),
            max_centroids=int(config["max_centroids_per_input_part"]),
            kmeans_iterations=int(config["kmeans_iterations"]),
            max_training_rows=int(config["max_training_rows_per_input_part"]),
            data_dir=data_dir,
            write_index=False,
        )
        session.commit_tree(data_dir)
    committed = tuple(
        _redescribe(root, descriptor) for descriptor in written.data_descriptors
    )
    descriptor_map = {
        descriptor.relative_path: _descriptor_dict(descriptor)
        for descriptor in committed
    }
    routing_rows = []
    for row in written.layout.routing_rows(descriptors=descriptor_map):
        payload = dict(row)
        payload.update(
            {
                "jurisdiction_code": part.jurisdiction_code,
                "source_input_digest": part.input_digest,
                "source_part_index": part.part_index,
            }
        )
        routing_rows.append(payload)
    record = {
        "cluster_count": written.layout.cluster_count,
        "cluster_id_offset": cluster_offset,
        "data_descriptors": [_descriptor_dict(descriptor) for descriptor in committed],
        "global_document_index_offset": document_offset,
        "global_shard_id_offset": shard_offset,
        "input_digest": part.input_digest,
        "layout": written.layout.manifest_config(),
        "routing_rows": routing_rows,
        "row_count": part.row_count,
        "shard_count": written.layout.shard_count,
        "source_id": part.source_id,
    }
    _validate_part_record(
        record,
        part=part,
        root=root,
        cluster_offset=cluster_offset,
        shard_offset=shard_offset,
        document_offset=document_offset,
    )
    return record


def _iter_locator_records(
    records: Sequence[Mapping[str, Any]], *, root: Path
) -> Iterator[dict[str, Any]]:
    pq = _parquet()
    for record in records:
        routes = sorted(
            (dict(item) for item in record["routing_rows"]),
            key=lambda row: int(row["shard_id"]),
        )
        for route in routes:
            relative_path = str(route["relative_path"])
            path = confine_path(root, relative_path)
            rows = pq.read_table(
                path,
                columns=[
                    "chunk_in_cluster",
                    "cluster_id",
                    "document_index",
                    "entry_cid",
                ],
            ).to_pylist()
            for row_offset, row in enumerate(rows):
                entry_cid = str(row.get("entry_cid") or "")
                yield {
                    "chunk_in_cluster": int(row["chunk_in_cluster"]),
                    "cluster_id": int(row["cluster_id"]),
                    "document_index": int(row["document_index"]),
                    "entry_cid": entry_cid,
                    "first_key": entry_cid,
                    "global_shard_id": int(route["shard_id"]),
                    "jurisdiction_code": str(route["jurisdiction_code"]),
                    "relative_path": relative_path,
                    "row_offset": row_offset,
                    "source_part_index": int(route["source_part_index"]),
                }


def _locator_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row.get("entry_cid") or ""),)


def _iter_unique_sorted_locator_rows(path: Path) -> Iterator[dict[str, Any]]:
    previous_key: str | None = None
    for row in iter_jsonl(path):
        key = str(row.get("entry_cid") or "")
        if not key or (previous_key is not None and key <= previous_key):
            raise StateLawsVectorPhysicalError(
                "vector locator keys are empty, duplicated, or globally unordered"
            )
        previous_key = key
        yield row


def _centroid_rows(
    routing_rows: Sequence[Mapping[str, Any]], *, config: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    try:
        return compact_centroid_rows_from_routing(
            routing_rows,
            assignment=str(config["assignment"]),
            schema_version=CENTROID_SCHEMA_VERSION,
            context_fields=("jurisdiction_code", "source_part_index"),
        )
    except Exception as exc:
        raise StateLawsVectorPhysicalError(
            "combined centroid routing rows failed the shared contract"
        ) from exc


def _build_indexes_and_locators(
    records: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    build_digest: str,
    config: Mapping[str, Any],
    resume: bool,
    expected_rows: int,
) -> dict[str, Any]:
    routing_rows = tuple(
        dict(route) for record in records for route in record["routing_rows"]
    )
    if not routing_rows or len(routing_rows) > MAX_ROUTING_ROWS_PER_INDEX:
        raise StateLawsVectorPhysicalError(
            "combined vector routing rows must be 1..4096"
        )
    cluster_ids = sorted({int(row["cluster_id"]) for row in routing_rows})
    shard_ids = sorted(int(row["shard_id"]) for row in routing_rows)
    if cluster_ids != list(range(len(cluster_ids))) or shard_ids != list(
        range(len(shard_ids))
    ):
        raise StateLawsVectorPhysicalError(
            "combined centroid/shard identifiers are not globally dense"
        )
    centroid_rows = _centroid_rows(routing_rows, config=config)

    sort_root = confine_path(root, f"{DEFAULT_SORT_WORK_DIR}/{build_digest}")
    sorted_path = sort_root / "locators.sorted.jsonl"
    receipt = external_sort_to_file(
        _iter_locator_records(records, root=root),
        sorted_path,
        work_dir=sort_root / "work",
        key_fn=_locator_sort_key,
        family="locators",
        max_records_in_memory=int(config["max_sort_records_in_memory"]),
        resume=resume,
    )
    if receipt.interrupted or receipt.row_count != expected_rows:
        raise StateLawsVectorPhysicalError(
            "bounded locator sort did not conserve every vector key"
        )

    for relative_path in (
        CENTROID_DATA_PATH,
        VECTOR_INDEX_PATH,
        ENTRY_LOCATOR_DIR,
        ENTRY_LOCATOR_INDEX_PATH,
    ):
        if confine_path(root, relative_path).is_symlink():
            raise StateLawsVectorPhysicalError(
                f"refusing to replace symlinked vector index: {relative_path}"
            )

    locator_page_descriptors: list[ArtifactDescriptor] = []
    locator_rows: list[LocatorRow] = []
    locator_row_count = 0
    with atomic_staging(root, prefix=".state-laws-vector-index-") as session:
        centroid_path = session.confine(CENTROID_DATA_PATH)
        write_zstd_parquet(
            centroid_path,
            centroid_rows,
            config=ArtifactWriterConfig(max_rows_per_shard=MAX_ROUTING_ROWS_PER_INDEX),
        )
        centroid_descriptor = describe_file(
            centroid_path,
            root=session.staging_dir,
            row_count=len(centroid_rows),
            family=ArtifactFamily.CENTROIDS,
            schema_id=CENTROID_SCHEMA_VERSION,
            first_key=str(centroid_rows[0]["cluster_id"]),
            last_key=str(centroid_rows[-1]["cluster_id"]),
            metadata={"assignment": config["assignment"], "direct_columns": True},
        )

        vector_index_path = session.confine(VECTOR_INDEX_PATH)
        write_zstd_parquet(
            vector_index_path,
            routing_rows,
            config=ArtifactWriterConfig(max_rows_per_shard=MAX_ROUTING_ROWS_PER_INDEX),
        )
        vector_index_descriptor = describe_file(
            vector_index_path,
            root=session.staging_dir,
            row_count=len(routing_rows),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=VECTOR_ROUTING_SCHEMA_VERSION,
            metadata={"direct_columns": True, "kind": "semantic_centroids"},
        )

        partitions = stream_bounded_partitions(
            _iter_unique_sorted_locator_rows(sorted_path),
            max_rows=int(config["locator_page_size"]),
        )
        for page_index, page in enumerate(partitions):
            if page_index >= MAX_ROUTING_ROWS_PER_INDEX:
                raise StateLawsVectorPhysicalError(
                    "vector entry locator page count exceeds 4096"
                )
            keys = [str(row.get("entry_cid") or "") for row in page]
            if not keys or keys != sorted(keys) or len(keys) != len(set(keys)):
                raise StateLawsVectorPhysicalError(
                    "vector entry locator keys are missing, duplicated, or unsorted"
                )
            relative_path = f"{ENTRY_LOCATOR_DIR}/part-{page_index:06d}.parquet"
            page_path = session.confine(relative_path)
            write_zstd_parquet(
                page_path,
                page,
                config=ArtifactWriterConfig(
                    max_rows_per_shard=int(config["locator_page_size"])
                ),
            )
            descriptor = describe_file(
                page_path,
                root=session.staging_dir,
                row_count=len(page),
                family=ArtifactFamily.LOCATOR_INDEX,
                schema_id=LOCATOR_PAGE_SCHEMA_VERSION,
                first_key=keys[0],
                last_key=keys[-1],
                shard_id=page_index,
                metadata={"direct_columns": True, "exact_keys": True},
            )
            locator_page_descriptors.append(descriptor)
            locator_rows.append(
                LocatorRow(
                    relative_path=descriptor.relative_path,
                    sha256=descriptor.sha256,
                    size_bytes=descriptor.size_bytes,
                    row_count=descriptor.row_count,
                    shard_id=page_index,
                    first_key=keys[0],
                    last_key=keys[-1],
                    kind=KIND_VECTORS,
                    schema_version=LOCATOR_SCHEMA_VERSION,
                    content_cid=descriptor.content_cid,
                    page_index=page_index,
                    start_document_index=locator_row_count,
                    end_document_index=locator_row_count + len(page) - 1,
                    metadata={
                        "entry_locator_page_schema_version": LOCATOR_PAGE_SCHEMA_VERSION,
                    },
                )
            )
            locator_row_count += len(page)
        if locator_row_count != expected_rows or not locator_rows:
            raise StateLawsVectorPhysicalError(
                "vector entry locator did not conserve every key"
            )
        validated_locator_rows = validate_locator_ranges(
            locator_rows,
            kind=KIND_VECTORS,
            max_rows=MAX_ROUTING_ROWS_PER_INDEX,
        )
        locator_routes = [
            row.to_compact_index_row().to_dict() for row in validated_locator_rows
        ]

        locator_index_path = session.confine(ENTRY_LOCATOR_INDEX_PATH)
        write_zstd_parquet(
            locator_index_path,
            locator_routes,
            config=ArtifactWriterConfig(max_rows_per_shard=MAX_ROUTING_ROWS_PER_INDEX),
        )
        locator_index_descriptor = describe_file(
            locator_index_path,
            root=session.staging_dir,
            row_count=len(locator_routes),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=LOCATOR_META_SCHEMA_VERSION,
            metadata={"direct_columns": True, "kind": "vector_entry_locator"},
        )

        session.commit_file(CENTROID_DATA_PATH)
        session.commit_tree(ENTRY_LOCATOR_DIR)
        session.commit_file(VECTOR_INDEX_PATH)
        session.commit_file(ENTRY_LOCATOR_INDEX_PATH)

    centroid_descriptor = _redescribe(root, centroid_descriptor)
    vector_index_descriptor = _redescribe(root, vector_index_descriptor)
    locator_page_descriptors = [
        _redescribe(root, descriptor) for descriptor in locator_page_descriptors
    ]
    locator_index_descriptor = _redescribe(root, locator_index_descriptor)
    receipt_payload = receipt.to_dict()
    receipt_payload["output_path"] = sorted_path.relative_to(root).as_posix()
    return {
        "centroid_descriptor": _descriptor_dict(centroid_descriptor),
        "locator_index_descriptor": _descriptor_dict(locator_index_descriptor),
        "locator_page_descriptors": [
            _descriptor_dict(descriptor) for descriptor in locator_page_descriptors
        ],
        "sort_receipt": receipt_payload,
        "vector_index_descriptor": _descriptor_dict(vector_index_descriptor),
    }


def _validate_final(
    final: Mapping[str, Any],
    *,
    root: Path,
    expected_rows: int,
    records: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    build_digest: str,
) -> None:
    expected_routing = tuple(
        dict(route) for record in records for route in record["routing_rows"]
    )
    expected_centroids = _centroid_rows(expected_routing, config=config)
    centroid_descriptor = _verify_output_descriptor(
        root,
        final.get("centroid_descriptor") or {},
        label="centroid data",
    )
    if (
        centroid_descriptor.relative_path != CENTROID_DATA_PATH
        or centroid_descriptor.family is not ArtifactFamily.CENTROIDS
        or centroid_descriptor.schema_id != CENTROID_SCHEMA_VERSION
        or centroid_descriptor.row_count != len(expected_centroids)
    ):
        raise StateLawsVectorOutputDriftError("centroid descriptor coverage differs")
    centroid_rows = (
        _parquet().read_table(confine_path(root, CENTROID_DATA_PATH)).to_pylist()
    )
    if [canonical_json_dumps(row) for row in centroid_rows] != [
        canonical_json_dumps(row) for row in expected_centroids
    ]:
        raise StateLawsVectorOutputDriftError(
            "centroid rows differ from the combined routing index"
        )

    vector_index_descriptor = _verify_output_descriptor(
        root,
        final.get("vector_index_descriptor") or {},
        label="combined vector index",
    )
    if (
        vector_index_descriptor.relative_path != VECTOR_INDEX_PATH
        or vector_index_descriptor.family is not ArtifactFamily.ROUTING_INDEX
        or vector_index_descriptor.schema_id != VECTOR_ROUTING_SCHEMA_VERSION
        or vector_index_descriptor.row_count != len(expected_routing)
    ):
        raise StateLawsVectorOutputDriftError(
            "combined vector index descriptor contract differs"
        )
    actual_routing = (
        _parquet().read_table(confine_path(root, VECTOR_INDEX_PATH)).to_pylist()
    )
    routing_fields = (
        "centroid",
        "centroid_shard_count",
        "chunk_in_cluster",
        "cluster_id",
        "dimension",
        "jurisdiction_code",
        "relative_path",
        "row_count",
        "sha256",
        "shard_id",
        "size_bytes",
        "source_input_digest",
        "source_part_index",
    )
    if [
        canonical_json_dumps({field: row.get(field) for field in routing_fields})
        for row in actual_routing
    ] != [
        canonical_json_dumps({field: row.get(field) for field in routing_fields})
        for row in expected_routing
    ]:
        raise StateLawsVectorOutputDriftError(
            "combined vector index differs from completed vector parts"
        )

    pages = [
        dict(item)
        for item in final.get("locator_page_descriptors", [])
        if isinstance(item, Mapping)
    ]
    if (
        not pages
        or len(pages) > MAX_ROUTING_ROWS_PER_INDEX
        or sum(int(item.get("row_count") or 0) for item in pages) != expected_rows
    ):
        raise StateLawsVectorOutputDriftError(
            "vector locator page descriptor coverage differs"
        )
    receipt = final.get("sort_receipt")
    expected_sort_path = f"{DEFAULT_SORT_WORK_DIR}/{build_digest}/locators.sorted.jsonl"
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("family") != "locators"
        or receipt.get("status") != "complete"
        or receipt.get("interrupted") is not False
        or int(receipt.get("row_count") or -1) != expected_rows
        or int(receipt.get("records_consumed") or -1) != expected_rows
        or int(receipt.get("max_records_in_memory") or -1)
        != int(config["max_sort_records_in_memory"])
        or int(receipt.get("peak_resident_records") or -1)
        > int(config["max_sort_records_in_memory"])
        or str(receipt.get("output_path") or "") != expected_sort_path
        or _HEX_64_RE.fullmatch(str(receipt.get("output_digest") or "")) is None
    ):
        raise StateLawsVectorOutputDriftError("vector locator sort receipt differs")

    sorted_path = confine_path(root, expected_sort_path)
    if (
        sorted_path.is_symlink()
        or not sorted_path.is_file()
        or file_sha256(sorted_path) != receipt["output_digest"]
    ):
        raise StateLawsVectorOutputDriftError(
            "vector locator sorted stream digest differs"
        )
    sorted_rows = iter(iter_jsonl(sorted_path))
    locator_rows: list[LocatorRow] = []
    previous_key: str | None = None
    locator_row_count = 0
    for page_index, value in enumerate(pages):
        descriptor = _verify_output_descriptor(
            root, value, label=f"vector locator page {page_index}"
        )
        expected_page_path = f"{ENTRY_LOCATOR_DIR}/part-{page_index:06d}.parquet"
        if (
            descriptor.relative_path != expected_page_path
            or descriptor.family is not ArtifactFamily.LOCATOR_INDEX
            or descriptor.schema_id != LOCATOR_PAGE_SCHEMA_VERSION
            or descriptor.shard_id != page_index
        ):
            raise StateLawsVectorOutputDriftError(
                f"vector locator page descriptor contract differs at {page_index}"
            )
        page_rows = (
            _parquet().read_table(confine_path(root, expected_page_path)).to_pylist()
        )
        keys = [str(row.get("entry_cid") or "") for row in page_rows]
        if (
            len(page_rows) != descriptor.row_count
            or not keys
            or keys != sorted(keys)
            or len(keys) != len(set(keys))
            or descriptor.first_key != keys[0]
            or descriptor.last_key != keys[-1]
            or (previous_key is not None and keys[0] <= previous_key)
        ):
            raise StateLawsVectorOutputDriftError(
                f"vector locator page key coverage differs at {page_index}"
            )
        for row in page_rows:
            try:
                expected = next(sorted_rows)
            except StopIteration as exc:
                raise StateLawsVectorOutputDriftError(
                    "vector locator pages exceed the sorted source"
                ) from exc
            if canonical_json_dumps(row) != canonical_json_dumps(expected):
                raise StateLawsVectorOutputDriftError(
                    f"vector locator row differs at key {row.get('entry_cid')!r}"
                )
        locator_rows.append(
            LocatorRow(
                relative_path=descriptor.relative_path,
                sha256=descriptor.sha256,
                size_bytes=descriptor.size_bytes,
                row_count=descriptor.row_count,
                shard_id=page_index,
                first_key=keys[0],
                last_key=keys[-1],
                kind=KIND_VECTORS,
                schema_version=LOCATOR_SCHEMA_VERSION,
                content_cid=descriptor.content_cid,
                page_index=page_index,
                start_document_index=locator_row_count,
                end_document_index=locator_row_count + len(page_rows) - 1,
                metadata={
                    "entry_locator_page_schema_version": LOCATOR_PAGE_SCHEMA_VERSION,
                },
            )
        )
        locator_row_count += len(page_rows)
        previous_key = keys[-1]
    try:
        next(sorted_rows)
    except StopIteration:
        pass
    else:
        raise StateLawsVectorOutputDriftError(
            "vector locator pages omit rows from the sorted source"
        )
    validated = validate_locator_ranges(
        locator_rows,
        kind=KIND_VECTORS,
        max_rows=MAX_ROUTING_ROWS_PER_INDEX,
    )
    expected_locator_routes = [
        row.to_compact_index_row().to_dict() for row in validated
    ]
    locator_index_descriptor = _verify_output_descriptor(
        root,
        final.get("locator_index_descriptor") or {},
        label="vector locator meta index",
    )
    if (
        locator_index_descriptor.relative_path != ENTRY_LOCATOR_INDEX_PATH
        or locator_index_descriptor.family is not ArtifactFamily.ROUTING_INDEX
        or locator_index_descriptor.schema_id != LOCATOR_META_SCHEMA_VERSION
        or locator_index_descriptor.row_count != len(expected_locator_routes)
    ):
        raise StateLawsVectorOutputDriftError(
            "vector locator meta descriptor contract differs"
        )
    actual_locator_routes = (
        _parquet().read_table(confine_path(root, ENTRY_LOCATOR_INDEX_PATH)).to_pylist()
    )
    if [canonical_json_dumps(row) for row in actual_locator_routes] != [
        canonical_json_dumps(row) for row in expected_locator_routes
    ]:
        raise StateLawsVectorOutputDriftError(
            "vector locator meta index differs from locator pages"
        )


def _result_from_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    root: Path,
    checkpoint_path: Path,
    parent_entry_cids: Iterable[str],
    resumed_part_count: int,
    executed_part_count: int,
) -> StateLawsVectorPhysicalResult:
    completed = [
        dict(item)
        for item in checkpoint.get("completed_parts", [])
        if isinstance(item, Mapping)
    ]
    final = dict(checkpoint.get("final") or {})
    routing_rows = tuple(
        dict(route)
        for record in completed
        for route in record.get("routing_rows", [])
        if isinstance(route, Mapping)
    )
    data_descriptors = tuple(
        dict(descriptor)
        for record in completed
        for descriptor in record.get("data_descriptors", [])
        if isinstance(descriptor, Mapping)
    )
    inputs = [
        dict(item) for item in checkpoint.get("inputs", []) if isinstance(item, Mapping)
    ]
    return StateLawsVectorPhysicalResult(
        output_root=str(root),
        checkpoint_path=str(checkpoint_path),
        build_digest=str(checkpoint["build_digest"]),
        row_count=int(checkpoint["row_count"]),
        jurisdiction_count=len(
            {str(item.get("jurisdiction_code") or "") for item in inputs}
        ),
        input_part_count=len(inputs),
        resumed_part_count=resumed_part_count,
        executed_part_count=executed_part_count,
        cluster_count=sum(int(item["cluster_count"]) for item in completed),
        shard_count=sum(int(item["shard_count"]) for item in completed),
        vector_data_descriptors=data_descriptors,
        centroid_descriptor=dict(final["centroid_descriptor"]),
        vector_index_descriptor=dict(final["vector_index_descriptor"]),
        locator_page_descriptors=tuple(
            dict(item) for item in final["locator_page_descriptors"]
        ),
        locator_index_descriptor=dict(final["locator_index_descriptor"]),
        routing_rows=routing_rows,
        config=dict(checkpoint["config"]),
        model=dict(checkpoint["model"]),
        sort_receipt=dict(final["sort_receipt"]),
        parent_entry_cids=tuple(sorted(set(parent_entry_cids))),
        production_ready=True,
    )


def write_state_laws_vector_physical_layout(
    input_parts: Iterable[str | Path],
    output_root: str | Path,
    *,
    checkpoint_path: str | Path | None = None,
    seed: int = DEFAULT_VECTOR_KMEANS_SEED,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID,
    max_rows_per_centroid: int | None = None,
    target_rows_per_centroid: int = DEFAULT_TARGET_ROWS_PER_CENTROID,
    max_centroids: int = DEFAULT_MAX_CENTROIDS,
    kmeans_iterations: int = DEFAULT_KMEANS_ITERATIONS,
    max_training_rows: int = DEFAULT_TRAINING_ROWS,
    locator_page_size: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_sort_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    resume: bool = True,
) -> StateLawsVectorPhysicalResult:
    """Write query-ready vectors/centroid routes/exact-key locator indexes."""

    for name, value, maximum in (
        ("max_rows_per_shard", max_rows_per_shard, MAX_ROWS_PER_PHYSICAL_SHARD),
        (
            "max_shards_per_centroid",
            max_shards_per_centroid,
            MAX_VECTOR_SHARDS_PER_CENTROID,
        ),
        ("locator_page_size", locator_page_size, MAX_ROWS_PER_PHYSICAL_SHARD),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise StateLawsVectorPhysicalError(f"{name} must be 1..{maximum}")
    for name, value in (
        ("seed", seed),
        ("target_rows_per_centroid", target_rows_per_centroid),
        ("max_centroids", max_centroids),
        ("kmeans_iterations", kmeans_iterations),
        ("max_training_rows", max_training_rows),
        ("max_sort_records_in_memory", max_sort_records_in_memory),
    ):
        minimum = (
            0 if name == "seed" else (2 if name == "max_sort_records_in_memory" else 1)
        )
        if type(value) is not int or value < minimum:
            raise StateLawsVectorPhysicalError(
                f"{name} must be an integer >= {minimum}"
            )
    centroid_rows = (
        max_rows_per_shard * max_shards_per_centroid
        if max_rows_per_centroid is None
        else max_rows_per_centroid
    )
    if (
        type(centroid_rows) is not int
        or not 1 <= centroid_rows <= MAX_ROWS_PER_VECTOR_CENTROID
        or centroid_rows > max_rows_per_shard * max_shards_per_centroid
        or target_rows_per_centroid > centroid_rows
    ):
        raise StateLawsVectorPhysicalError(
            "max_rows_per_centroid/target_rows_per_centroid violate vector bounds"
        )
    if not isinstance(resume, bool):
        raise StateLawsVectorPhysicalError("resume must be a boolean")

    inputs = _prepare_inputs(input_parts)
    root = resolve_release_root(output_root, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = (
        Path(checkpoint_path).expanduser().resolve()
        if checkpoint_path is not None
        else confine_path(root, DEFAULT_CHECKPOINT_PATH)
    )
    if checkpoint.is_symlink():
        raise StateLawsVectorPhysicalError("vector checkpoint must not be a symlink")
    config = _build_config(
        seed=seed,
        max_rows_per_shard=max_rows_per_shard,
        max_shards_per_centroid=max_shards_per_centroid,
        max_rows_per_centroid=centroid_rows,
        target_rows_per_centroid=target_rows_per_centroid,
        max_centroids=max_centroids,
        kmeans_iterations=kmeans_iterations,
        max_training_rows=max_training_rows,
        locator_page_size=locator_page_size,
        max_sort_records_in_memory=max_sort_records_in_memory,
    )
    model = _model_manifest(inputs[0])
    build_digest = _build_digest(inputs, config)
    prior = _load_physical_checkpoint(checkpoint, resume=resume)
    if prior:
        _validate_checkpoint_identity(
            prior,
            build_digest=build_digest,
            config=config,
            model=model,
            inputs=inputs,
        )
    prior_values = prior.get("completed_parts") or []
    if not isinstance(prior_values, Sequence) or isinstance(
        prior_values, (str, bytes, bytearray)
    ):
        raise StateLawsVectorInputDriftError(
            "vector checkpoint completed_parts must be a sequence"
        )
    prior_parts: dict[str, dict[str, Any]] = {}
    for item in prior_values:
        if not isinstance(item, Mapping) or not str(item.get("source_id") or ""):
            raise StateLawsVectorInputDriftError(
                "vector checkpoint contains a malformed completed part"
            )
        source_id = str(item["source_id"])
        if source_id in prior_parts:
            raise StateLawsVectorInputDriftError(
                "vector checkpoint contains duplicate completed parts"
            )
        prior_parts[source_id] = dict(item)
    expected_source_ids = {part.source_id for part in inputs}
    if set(prior_parts).difference(expected_source_ids):
        raise StateLawsVectorInputDriftError(
            "vector checkpoint contains stale completed parts"
        )

    completed: list[dict[str, Any]] = []
    cluster_offset = 0
    shard_offset = 0
    document_offset = 0
    resumed_count = 0
    executed_count = 0
    if not prior:
        atomic_write_canonical_json(
            checkpoint,
            _checkpoint_payload(
                build_digest=build_digest,
                config=config,
                model=model,
                inputs=inputs,
                completed_parts=(),
                status="building",
            ),
        )

    for ordinal, part in enumerate(inputs):
        existing = prior_parts.get(part.source_id)
        if existing is not None:
            _validate_part_record(
                existing,
                part=part,
                root=root,
                cluster_offset=cluster_offset,
                shard_offset=shard_offset,
                document_offset=document_offset,
            )
            record = existing
            resumed_count += 1
        else:
            record = _write_part(
                part,
                root=root,
                ordinal=ordinal,
                cluster_offset=cluster_offset,
                shard_offset=shard_offset,
                document_offset=document_offset,
                config=config,
            )
            executed_count += 1
        completed.append(record)
        cluster_offset += int(record["cluster_count"])
        shard_offset += int(record["shard_count"])
        document_offset += part.row_count
        if prior.get("status") != "complete" or executed_count > 0:
            atomic_write_canonical_json(
                checkpoint,
                _checkpoint_payload(
                    build_digest=build_digest,
                    config=config,
                    model=model,
                    inputs=inputs,
                    completed_parts=completed,
                    status="building",
                ),
            )

    if (
        prior.get("status") == "complete"
        and len(completed) == len(inputs)
        and isinstance(prior.get("final"), Mapping)
        and executed_count == 0
    ):
        _validate_final(
            prior["final"],
            root=root,
            expected_rows=document_offset,
            records=completed,
            config=config,
            build_digest=build_digest,
        )
        return _result_from_checkpoint(
            prior,
            root=root,
            checkpoint_path=checkpoint,
            parent_entry_cids=(
                parent_entry_cid
                for part in inputs
                for parent_entry_cid in part.parent_entry_cids
            ),
            resumed_part_count=resumed_count,
            executed_part_count=0,
        )

    final = _build_indexes_and_locators(
        completed,
        root=root,
        build_digest=build_digest,
        config=config,
        resume=resume,
        expected_rows=document_offset,
    )
    _validate_final(
        final,
        root=root,
        expected_rows=document_offset,
        records=completed,
        config=config,
        build_digest=build_digest,
    )
    payload = _checkpoint_payload(
        build_digest=build_digest,
        config=config,
        model=model,
        inputs=inputs,
        completed_parts=completed,
        status="complete",
        final=final,
    )
    atomic_write_canonical_json(checkpoint, payload)
    return _result_from_checkpoint(
        payload,
        root=root,
        checkpoint_path=checkpoint,
        parent_entry_cids=(
            parent_entry_cid
            for part in inputs
            for parent_entry_cid in part.parent_entry_cids
        ),
        resumed_part_count=resumed_count,
        executed_part_count=executed_count,
    )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CENTROID_DATA_PATH",
    "CENTROID_SCHEMA_VERSION",
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_CHECKPOINT_PATH",
    "ENTRY_LOCATOR_DIR",
    "ENTRY_LOCATOR_INDEX_PATH",
    "LOCATOR_META_SCHEMA_VERSION",
    "LOCATOR_PAGE_SCHEMA_VERSION",
    "PROJECTION_EMBEDDINGS_ALLOWED",
    "SCHEMA_VERSION",
    "VECTOR_DATA_DIR",
    "VECTOR_INDEX_PATH",
    "ProjectionEmbeddingRejectedError",
    "StateLawsVectorInputDriftError",
    "StateLawsVectorOutputDriftError",
    "StateLawsVectorPhysicalError",
    "StateLawsVectorPhysicalResult",
    "write_state_laws_vector_physical_layout",
]
