"""Streaming, resumable production GTE-small embeddings for state laws.

The public writer consumes its source once, spills an ordered chunk stream
through the shared external-sort primitive, and embeds one physical Parquet
part at a time.  Resume is allowed only after descriptor, direct-column,
document-index, model-pin, input-hash, and vector checks all close.

This module never publishes and never treats fixture/projection output as a
production candidate.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_DIMENSION,
    AdmittedChunk,
    EmbeddingFunction,
    ModelFactory,
    OpenUsLawEmbeddingConfig,
    OpenUsLawEmbeddingGenerator,
    collect_runtime_evidence,
    default_embedding_config,
    input_content_hash,
    production_inference_evidence_satisfies_contract,
    resolve_embedder,
    select_device,
    validate_vector_dimension,
    validate_vector_norm,
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    validate_jurisdiction,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    describe_file,
    verify_descriptor,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    ExternalSortError,
    external_sort_to_file,
    iter_jsonl,
    stream_bounded_partitions,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactDescriptor,
    ArtifactFamily,
    canonical_json_dumps,
    content_sha256,
)

SCHEMA_VERSION: Final = "state-laws-partitioned-embeddings/v1"
PART_SCHEMA_VERSION: Final = "state-laws-partitioned-embedding-row/v1"
TASK_ID: Final = "LCR-084-EMBED"
DEFAULT_SORT_WORK_DIR: Final = "checkpoints/embedding_sort"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
LEGACY_MATERIALIZED_EMBEDDING_PATH_PRODUCTION_READY: Final = False
STREAMING_EMBEDDING_STORE_PRODUCTION_READY: Final = True

_REQUIRED_PART_COLUMNS: Final = frozenset(
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


class StateLawsEmbeddingStoreError(ValueError):
    """Raised when a partitioned embedding store cannot close safely."""


class StateLawsEmbeddingInputDriftError(StateLawsEmbeddingStoreError):
    """Raised when a resume checkpoint no longer describes the active input."""


class StateLawsEmbeddingOutputDriftError(StateLawsEmbeddingStoreError):
    """Raised when a recorded embedding artifact fails integrity checks."""


@dataclass(frozen=True, slots=True)
class _PartSpec:
    part_index: int
    row_count: int
    document_index_start: int
    input_digest: str
    first_key: str
    last_key: str
    path: Path


@dataclass(frozen=True, slots=True)
class EmbeddingStoreResult:
    jurisdiction_code: str
    output_root: str
    checkpoint_path: str
    row_count: int
    part_count: int
    resumed_part_count: int
    executed_part_count: int
    descriptors: tuple[Mapping[str, Any], ...]
    config: Mapping[str, Any]
    inference: Mapping[str, Any]
    sort_receipt: Mapping[str, Any]
    production_ready: bool
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_path": self.checkpoint_path,
            "config": dict(self.config),
            "descriptors": [dict(item) for item in self.descriptors],
            "executed_part_count": self.executed_part_count,
            "inference": dict(self.inference),
            "jurisdiction_code": self.jurisdiction_code,
            "output_root": self.output_root,
            "part_count": self.part_count,
            "production_ready": self.production_ready,
            "resumed_part_count": self.resumed_part_count,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "sort_receipt": dict(self.sort_receipt),
            "task_id": TASK_ID,
        }


def _coerce_chunk(
    value: AdmittedChunk | Mapping[str, Any],
    *,
    jurisdiction_code: str,
    position: int,
) -> AdmittedChunk | None:
    if isinstance(value, AdmittedChunk):
        chunk = value
    elif isinstance(value, Mapping):
        disposition = str(value.get("disposition") or "admitted").lower()
        if disposition != "admitted" or value.get("is_recovery") is True:
            return None
        payload = dict(value)
        payload["text"] = str(
            payload.get("text")
            or payload.get("exclusive_text")
            or payload.get("body")
            or ""
        )
        payload["entry_cid"] = payload.get("parent_entry_cid") or payload.get(
            "entry_cid"
        )
        extras = dict(payload.get("extra_fields") or {})
        extras["jurisdiction_code"] = jurisdiction_code
        payload["extra_fields"] = extras
        chunk = AdmittedChunk.from_mapping(payload)
    else:
        raise StateLawsEmbeddingStoreError(
            f"rows[{position}] must be an admitted chunk or mapping"
        )
    if not chunk.text.strip():
        raise StateLawsEmbeddingStoreError(
            f"empty admitted chunk text: {chunk.chunk_cid}"
        )
    if not chunk.entry_cid:
        raise StateLawsEmbeddingStoreError(
            f"admitted chunk lacks parent entry_cid: {chunk.chunk_cid}"
        )
    return chunk


def _iter_chunk_envelopes(
    rows: Iterable[AdmittedChunk | Mapping[str, Any]],
    *,
    jurisdiction_code: str,
) -> Iterator[dict[str, Any]]:
    if isinstance(rows, (str, bytes, bytearray)):
        raise StateLawsEmbeddingStoreError("embedding rows must be an iterable")
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise StateLawsEmbeddingStoreError(
            "embedding rows must be an iterable"
        ) from exc
    for position, value in enumerate(iterator):
        chunk = _coerce_chunk(
            value,
            jurisdiction_code=jurisdiction_code,
            position=position,
        )
        if chunk is not None:
            yield {"chunk": chunk.to_dict(), "chunk_cid": chunk.chunk_cid}


def _chunk_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row.get("chunk_cid") or ""),)


def _iter_part_pages(
    sorted_path: Path,
    *,
    rows_per_part: int,
) -> Iterator[tuple[AdmittedChunk, ...]]:
    previous_key: str | None = None

    def unique_chunks() -> Iterator[dict[str, Any]]:
        nonlocal previous_key
        for envelope in iter_jsonl(sorted_path):
            payload = envelope.get("chunk")
            if not isinstance(payload, Mapping):
                raise StateLawsEmbeddingStoreError(
                    "sorted embedding input contains a malformed chunk envelope"
                )
            chunk = AdmittedChunk.from_mapping(payload)
            if chunk.chunk_cid != str(envelope.get("chunk_cid") or ""):
                raise StateLawsEmbeddingStoreError(
                    "sorted embedding chunk identity is unbound"
                )
            if previous_key is not None and chunk.chunk_cid <= previous_key:
                if chunk.chunk_cid == previous_key:
                    raise StateLawsEmbeddingStoreError(
                        f"duplicate admitted chunk_cid: {chunk.chunk_cid}"
                    )
                raise StateLawsEmbeddingStoreError(
                    "sorted embedding chunk order regressed"
                )
            previous_key = chunk.chunk_cid
            yield {"chunk": chunk.to_dict()}

    for page in stream_bounded_partitions(unique_chunks(), max_rows=rows_per_part):
        yield tuple(AdmittedChunk.from_mapping(row["chunk"]) for row in page)


def _part_input_digest(
    chunks: Sequence[AdmittedChunk],
    config: OpenUsLawEmbeddingConfig,
    *,
    document_index_start: int,
) -> str:
    return content_sha256(
        canonical_json_dumps(
            {
                "config_digest": config.digest,
                "document_index_start": document_index_start,
                "rows": [
                    {
                        "chunk": chunk.to_dict(),
                        "input_hash": input_content_hash(
                            chunk.resolve_input_text(config.input_fields)
                        ),
                    }
                    for chunk in chunks
                ],
                "schema_version": SCHEMA_VERSION,
            }
        )
    )


def _collect_part_specs(
    sorted_path: Path,
    *,
    data_dir: Path,
    rows_per_part: int,
    config: OpenUsLawEmbeddingConfig,
) -> tuple[_PartSpec, ...]:
    specs: list[_PartSpec] = []
    document_index_start = 0
    for part_index, chunks in enumerate(
        _iter_part_pages(sorted_path, rows_per_part=rows_per_part)
    ):
        specs.append(
            _PartSpec(
                part_index=part_index,
                row_count=len(chunks),
                document_index_start=document_index_start,
                input_digest=_part_input_digest(
                    chunks,
                    config,
                    document_index_start=document_index_start,
                ),
                first_key=chunks[0].chunk_cid,
                last_key=chunks[-1].chunk_cid,
                path=data_dir / f"part-{part_index:06d}.parquet",
            )
        )
        document_index_start += len(chunks)
    return tuple(specs)


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise StateLawsEmbeddingStoreError(
            f"embedding checkpoint must be a regular file: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsEmbeddingStoreError(
            f"invalid embedding checkpoint: {path}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StateLawsEmbeddingStoreError("embedding checkpoint must be an object")
    return dict(payload)


def _checkpoint_parts(checkpoint: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    values = checkpoint.get("parts") or []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise StateLawsEmbeddingInputDriftError(
            "embedding checkpoint parts must be a sequence"
        )
    parts: dict[int, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, Mapping) or type(value.get("part_index")) is not int:
            raise StateLawsEmbeddingInputDriftError(
                "embedding checkpoint contains a malformed part record"
            )
        index = int(value["part_index"])
        if index < 0 or index in parts:
            raise StateLawsEmbeddingInputDriftError(
                "embedding checkpoint part indexes are duplicated or negative"
            )
        parts[index] = dict(value)
    return parts


def _parquet() -> Any:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise StateLawsEmbeddingStoreError(
            "pyarrow is required for the state-law embedding store"
        ) from exc
    return pq


def _validate_recorded_part(
    record: Mapping[str, Any] | None,
    *,
    spec: _PartSpec,
    chunks: Sequence[AdmittedChunk],
    root: Path,
    config: OpenUsLawEmbeddingConfig,
    jurisdiction: str,
    inference_digest: str,
) -> bool:
    if record is None:
        return False
    if (
        record.get("input_digest") != spec.input_digest
        or int(record.get("row_count") or -1) != spec.row_count
        or int(record.get("document_index_start", -1)) != spec.document_index_start
        or record.get("inference_digest") != inference_digest
    ):
        return False
    if not isinstance(record.get("descriptor"), Mapping):
        raise StateLawsEmbeddingOutputDriftError(
            f"embedding descriptor is missing for part {spec.part_index}"
        )
    try:
        descriptor = ArtifactDescriptor.from_mapping(record["descriptor"])
        verified_path = verify_descriptor(root, descriptor)
    except Exception as exc:
        raise StateLawsEmbeddingOutputDriftError(
            f"embedding output drift for part {spec.part_index}"
        ) from exc
    expected_relative = spec.path.relative_to(root).as_posix()
    if (
        verified_path != spec.path
        or descriptor.relative_path != expected_relative
        or descriptor.family is not ArtifactFamily.VECTORS
        or descriptor.schema_id != PART_SCHEMA_VERSION
        or descriptor.row_count != spec.row_count
        or descriptor.first_key != spec.first_key
        or descriptor.last_key != spec.last_key
        or descriptor.shard_id != spec.part_index
        or descriptor.metadata.get("jurisdiction_code") != jurisdiction
        or descriptor.metadata.get("stage") != "embedding_store"
        or record.get("sha256") != descriptor.sha256
    ):
        raise StateLawsEmbeddingOutputDriftError(
            f"embedding descriptor contract drift for part {spec.part_index}"
        )

    pq = _parquet()
    parquet = pq.ParquetFile(spec.path)
    columns = set(parquet.schema_arrow.names)
    if "record_json" in columns or not _REQUIRED_PART_COLUMNS.issubset(columns):
        raise StateLawsEmbeddingOutputDriftError(
            f"embedding part {spec.part_index} is not direct-column Parquet"
        )
    if int(parquet.metadata.num_rows) != spec.row_count:
        raise StateLawsEmbeddingOutputDriftError(
            f"embedding row count drift for part {spec.part_index}"
        )
    rows = pq.read_table(spec.path, columns=sorted(_REQUIRED_PART_COLUMNS)).to_pylist()
    for offset, (row, chunk) in enumerate(zip(rows, chunks, strict=True)):
        text = chunk.resolve_input_text(config.input_fields)
        expected_document_index = spec.document_index_start + offset
        if (
            row.get("chunk_cid") != chunk.chunk_cid
            or row.get("entry_cid") != chunk.chunk_cid
            or row.get("chunk_id") != chunk.chunk_id
            or row.get("parent_entry_cid") != chunk.entry_cid
            or row.get("input_hash") != input_content_hash(text)
            or row.get("config_cid") != config.config_cid
            or row.get("jurisdiction_code") != jurisdiction
            or row.get("model_id") != config.model_id
            or row.get("model_revision") != config.model_revision
            or row.get("pooling") != config.pooling
            or row.get("normalization") != config.normalization
            or row.get("vector_space_id") != config.vector_space_id
            or row.get("schema_version") != PART_SCHEMA_VERSION
            or int(row.get("dimension") or 0) != PINNED_DIMENSION
            or int(row.get("document_index", -1)) != expected_document_index
        ):
            raise StateLawsEmbeddingOutputDriftError(
                f"embedding row contract drift for {chunk.chunk_cid}"
            )
        try:
            vector = validate_vector_dimension(
                row.get("embedding"),
                dimension=PINNED_DIMENSION,
                name=f"embedding[{chunk.chunk_cid}]",
            )
            norm = validate_vector_norm(
                vector,
                normalization=config.normalization,
                name=f"embedding[{chunk.chunk_cid}]",
            )
        except Exception as exc:
            raise StateLawsEmbeddingOutputDriftError(
                f"embedding vector drift for {chunk.chunk_cid}"
            ) from exc
        if norm <= 0.0:
            raise StateLawsEmbeddingOutputDriftError(
                f"embedding vector is zero for {chunk.chunk_cid}"
            )
    return True


def _checkpoint_payload(
    *,
    config: OpenUsLawEmbeddingConfig,
    inference: Mapping[str, Any],
    jurisdiction: str,
    parts: Sequence[Mapping[str, Any]],
    production_ready: bool,
    row_count: int,
    sort_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "config": config.to_dict(),
        "config_digest": config.digest,
        "inference": dict(inference),
        "jurisdiction_code": jurisdiction,
        "parts": sorted(
            (dict(item) for item in parts), key=lambda item: item["part_index"]
        ),
        "production_ready": production_ready,
        "row_count": row_count,
        "schema_version": SCHEMA_VERSION,
        "sort_receipt": dict(sort_receipt),
        "task_id": TASK_ID,
    }


def build_state_laws_embedding_store(
    rows: Iterable[AdmittedChunk | Mapping[str, Any]],
    output_root: str | Path,
    *,
    jurisdiction_code: str,
    checkpoint_path: str | Path | None = None,
    config: OpenUsLawEmbeddingConfig | None = None,
    embedder: EmbeddingFunction | None = None,
    model_factory: ModelFactory | None = None,
    rows_per_part: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_sort_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    resume: bool = True,
) -> EmbeddingStoreResult:
    """Embed one jurisdiction from a one-shot iterable into bounded parts."""

    jurisdiction = validate_jurisdiction(jurisdiction_code, name="jurisdiction_code")
    if (
        type(rows_per_part) is not int
        or not 1 <= rows_per_part <= MAX_ROWS_PER_PHYSICAL_SHARD
    ):
        raise StateLawsEmbeddingStoreError(
            f"rows_per_part must be 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if type(max_sort_records_in_memory) is not int or max_sort_records_in_memory < 2:
        raise StateLawsEmbeddingStoreError(
            "max_sort_records_in_memory must be an integer >= 2"
        )
    if not isinstance(resume, bool):
        raise StateLawsEmbeddingStoreError("resume must be a boolean")

    selected = config or default_embedding_config()
    root = Path(output_root).expanduser().resolve()
    data_dir = root / "embeddings" / f"jurisdiction={jurisdiction}"
    data_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = (
        Path(checkpoint_path).expanduser().resolve()
        if checkpoint_path is not None
        else root / "checkpoints" / "embeddings" / f"{jurisdiction}.json"
    )
    if ckpt_path.is_symlink():
        raise StateLawsEmbeddingStoreError("embedding checkpoint must not be a symlink")

    sort_root = root / DEFAULT_SORT_WORK_DIR / jurisdiction / selected.digest
    sorted_path = sort_root / "chunks.sorted.jsonl"
    try:
        receipt = external_sort_to_file(
            _iter_chunk_envelopes(rows, jurisdiction_code=jurisdiction),
            sorted_path,
            work_dir=sort_root / "work",
            key_fn=_chunk_sort_key,
            family="chunks",
            max_records_in_memory=max_sort_records_in_memory,
            # External-sort resume is source-position based.  This public API
            # receives an unbound iterable, so always consume it exactly once.
            resume=False,
        )
    except ExternalSortError as exc:
        raise StateLawsEmbeddingStoreError(
            "bounded embedding input sort failed"
        ) from exc
    if receipt.interrupted or receipt.row_count < 1:
        raise StateLawsEmbeddingStoreError("no admitted chunks remain")
    if (
        receipt.records_consumed != receipt.row_count
        or receipt.peak_resident_records > max_sort_records_in_memory
    ):
        raise StateLawsEmbeddingStoreError(
            "bounded embedding input sort violated conservation or memory bounds"
        )
    sort_receipt = receipt.to_dict()
    sort_receipt["output_path"] = sorted_path.relative_to(root).as_posix()

    specs = _collect_part_specs(
        sorted_path,
        data_dir=data_dir,
        rows_per_part=rows_per_part,
        config=selected,
    )
    row_count = sum(spec.row_count for spec in specs)
    if row_count != receipt.row_count or not specs:
        raise StateLawsEmbeddingStoreError(
            "embedding partitions did not conserve the sorted input"
        )

    checkpoint = _load_checkpoint(ckpt_path) if resume else {}
    if checkpoint and (
        checkpoint.get("schema_version") != SCHEMA_VERSION
        or checkpoint.get("config_digest") != selected.digest
        or checkpoint.get("jurisdiction_code") != jurisdiction
    ):
        raise StateLawsEmbeddingInputDriftError(
            "embedding checkpoint does not match schema, pin, or jurisdiction"
        )
    prior_parts = _checkpoint_parts(checkpoint) if checkpoint else {}
    expected_indexes = {spec.part_index for spec in specs}
    if set(prior_parts).difference(expected_indexes):
        raise StateLawsEmbeddingInputDriftError(
            "embedding checkpoint contains stale parts outside the active input"
        )
    expected_paths = {spec.path for spec in specs}
    stale_paths = {
        path.resolve()
        for path in data_dir.glob("part-*.parquet")
        if path.resolve() not in expected_paths
    }
    if stale_paths:
        raise StateLawsEmbeddingInputDriftError(
            "embedding directory contains stale parts outside the active input"
        )

    inference = dict(checkpoint.get("inference") or {})
    checkpoint_inference_digest = content_sha256(canonical_json_dumps(inference))
    resumable: set[int] = set()
    for spec, chunks in zip(
        specs,
        _iter_part_pages(sorted_path, rows_per_part=rows_per_part),
        strict=True,
    ):
        if resume and _validate_recorded_part(
            prior_parts.get(spec.part_index),
            spec=spec,
            chunks=chunks,
            root=root,
            config=selected,
            jurisdiction=jurisdiction,
            inference_digest=checkpoint_inference_digest,
        ):
            resumable.add(spec.part_index)

    chosen: EmbeddingFunction | None = None
    generator: OpenUsLawEmbeddingGenerator | None = None
    if len(resumable) != len(specs):
        selected_device, fallback_applied = select_device(
            selected.device, fallback=selected.device_fallback
        )
        chosen, truncation, model_files, embedder_kind, real_inference = (
            resolve_embedder(
                selected,
                embedder=embedder,
                device=selected_device,
                model_factory=model_factory,
            )
        )
        generator = OpenUsLawEmbeddingGenerator(selected, embedder=chosen)
        active_inference = {
            "device": {
                "fallback_applied": fallback_applied,
                "requested": selected.device,
                "runtime": collect_runtime_evidence(selected_device),
                "selected": selected_device,
            },
            "embedder_kind": embedder_kind,
            "model_file_evidence": model_files,
            "real_inference": real_inference,
            "truncation": truncation.to_dict(),
            "truncation_satisfies_contract": truncation.satisfies_contract,
        }
        active_digest = content_sha256(canonical_json_dumps(active_inference))
        if resumable and active_digest != checkpoint_inference_digest:
            resumable.clear()
        inference = active_inference
    inference_digest = content_sha256(canonical_json_dumps(inference))

    completed_parts: list[dict[str, Any]] = []
    descriptors: list[Mapping[str, Any]] = []
    executed = 0
    for spec, chunks in zip(
        specs,
        _iter_part_pages(sorted_path, rows_per_part=rows_per_part),
        strict=True,
    ):
        if spec.part_index in resumable:
            record = dict(prior_parts[spec.part_index])
            completed_parts.append(record)
            descriptors.append(dict(record["descriptor"]))
            continue
        assert chosen is not None and generator is not None
        output_rows: list[dict[str, Any]] = []
        for batch_start in range(0, len(chunks), selected.batch_size):
            batch = chunks[batch_start : batch_start + selected.batch_size]
            texts = [chunk.resolve_input_text(selected.input_fields) for chunk in batch]
            vectors = generator.embed_texts(texts, embedder=chosen)
            for offset, (chunk, text, vector) in enumerate(
                zip(batch, texts, vectors, strict=True)
            ):
                output_rows.append(
                    {
                        "chunk_cid": chunk.chunk_cid,
                        "chunk_id": chunk.chunk_id,
                        "config_cid": selected.config_cid,
                        "dimension": PINNED_DIMENSION,
                        "document_index": (
                            spec.document_index_start + batch_start + offset
                        ),
                        "embedding": list(vector),
                        "entry_cid": chunk.chunk_cid,
                        "input_hash": input_content_hash(text),
                        "jurisdiction_code": jurisdiction,
                        "model_id": selected.model_id,
                        "model_revision": selected.model_revision,
                        "normalization": selected.normalization,
                        "parent_entry_cid": chunk.entry_cid,
                        "pooling": selected.pooling,
                        "schema_version": PART_SCHEMA_VERSION,
                        "vector_space_id": selected.vector_space_id,
                    }
                )
        write_zstd_parquet(
            spec.path,
            output_rows,
            max_rows=rows_per_part,
            config=ArtifactWriterConfig(max_rows_per_shard=rows_per_part),
        )
        descriptor = describe_file(
            spec.path,
            root=root,
            row_count=len(output_rows),
            family=ArtifactFamily.VECTORS,
            schema_id=PART_SCHEMA_VERSION,
            first_key=spec.first_key,
            last_key=spec.last_key,
            shard_id=spec.part_index,
            metadata={"jurisdiction_code": jurisdiction, "stage": "embedding_store"},
        ).to_dict()
        record = {
            "descriptor": descriptor,
            "document_index_start": spec.document_index_start,
            "inference_digest": inference_digest,
            "input_digest": spec.input_digest,
            "part_index": spec.part_index,
            "row_count": len(output_rows),
            "sha256": descriptor["sha256"],
        }
        _validate_recorded_part(
            record,
            spec=spec,
            chunks=chunks,
            root=root,
            config=selected,
            jurisdiction=jurisdiction,
            inference_digest=inference_digest,
        )
        completed_parts.append(record)
        descriptors.append(descriptor)
        executed += 1
        write_json_atomic(
            ckpt_path,
            _checkpoint_payload(
                config=selected,
                inference=inference,
                jurisdiction=jurisdiction,
                parts=completed_parts,
                production_ready=False,
                row_count=row_count,
                sort_receipt=sort_receipt,
            ),
        )

    production_ready = bool(
        selected.may_authorize_release
        and production_inference_evidence_satisfies_contract(inference)
        and len(descriptors) == len(specs)
        and sum(int(item.get("row_count") or 0) for item in descriptors) == row_count
        and all(
            record.get("inference_digest") == inference_digest
            for record in completed_parts
        )
    )
    payload = _checkpoint_payload(
        config=selected,
        inference=inference,
        jurisdiction=jurisdiction,
        parts=completed_parts,
        production_ready=production_ready,
        row_count=row_count,
        sort_receipt=sort_receipt,
    )
    write_json_atomic(ckpt_path, payload)
    return EmbeddingStoreResult(
        jurisdiction_code=jurisdiction,
        output_root=str(root),
        checkpoint_path=str(ckpt_path),
        row_count=row_count,
        part_count=len(specs),
        resumed_part_count=len(resumable),
        executed_part_count=executed,
        descriptors=tuple(descriptors),
        config=selected.to_dict(),
        inference=inference,
        sort_receipt=sort_receipt,
        production_ready=production_ready,
    )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "DEFAULT_SORT_WORK_DIR",
    "LEGACY_MATERIALIZED_EMBEDDING_PATH_PRODUCTION_READY",
    "PART_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "STREAMING_EMBEDDING_STORE_PRODUCTION_READY",
    "EmbeddingStoreResult",
    "StateLawsEmbeddingInputDriftError",
    "StateLawsEmbeddingOutputDriftError",
    "StateLawsEmbeddingStoreError",
    "build_state_laws_embedding_store",
]
