"""Focused production physical-vector tests for the state-law pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    default_embedding_config,
    input_content_hash,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    PART_SCHEMA_VERSION as EMBEDDING_PART_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    SCHEMA_VERSION as EMBEDDING_STORE_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_query import (
    StateLawsQueryClient,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vector_physical import (
    CENTROID_DATA_PATH,
    ENTRY_LOCATOR_INDEX_PATH,
    VECTOR_INDEX_PATH,
    ProjectionEmbeddingRejectedError,
    StateLawsVectorInputDriftError,
    StateLawsVectorOutputDriftError,
    write_state_laws_vector_physical_layout,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    atomic_write_canonical_json,
    describe_file,
    verify_descriptor,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import QueryLimits
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    ArtifactDescriptor,
    ArtifactFamily,
    canonical_json_dumps,
    content_sha256,
)

PINNED_RELEASE_REVISION = "a" * 40


def _unit(axis: int, *, sign: float = 1.0) -> list[float]:
    values = [0.0] * PINNED_DIMENSION
    values[axis] = sign
    return values


def _write_source_part(
    source_root: Path,
    jurisdiction: str,
    vectors: list[list[float]],
) -> Path:
    config = default_embedding_config()
    path = (
        source_root
        / "embeddings"
        / f"jurisdiction={jurisdiction}"
        / "part-000000.parquet"
    )
    rows: list[dict[str, Any]] = []
    for index, vector in enumerate(vectors):
        suffix = chr(ord("a") + index)
        entry_cid = f"chunk-{jurisdiction.lower()}-{suffix}"
        text = f"{jurisdiction} section {suffix}"
        rows.append(
            {
                "chunk_cid": entry_cid,
                "chunk_id": f"{jurisdiction}:{index}",
                "config_cid": config.config_cid,
                "dimension": PINNED_DIMENSION,
                "document_index": index,
                "embedding": vector,
                "entry_cid": entry_cid,
                "input_hash": input_content_hash(text),
                "jurisdiction_code": jurisdiction,
                "model_id": PINNED_MODEL_ID,
                "model_revision": PINNED_MODEL_REVISION,
                "normalization": "l2",
                "parent_entry_cid": f"parent-{jurisdiction.lower()}-{suffix}",
                "pooling": "mean",
                "schema_version": EMBEDDING_PART_SCHEMA_VERSION,
                "vector_space_id": config.vector_space_id,
            }
        )
    write_zstd_parquet(
        path,
        rows,
        config=ArtifactWriterConfig(max_rows_per_shard=len(rows)),
    )
    descriptor = describe_file(
        path,
        root=source_root,
        row_count=len(rows),
        family=ArtifactFamily.VECTORS,
        schema_id=EMBEDDING_PART_SCHEMA_VERSION,
        first_key=str(rows[0]["entry_cid"]),
        last_key=str(rows[-1]["entry_cid"]),
        shard_id=0,
        metadata={"jurisdiction_code": jurisdiction, "stage": "embedding_store"},
    )
    inference = {
        "device": {
            "runtime": {
                "sentence_transformers_available": True,
                "sentence_transformers_version": "fixture-contract",
                "torch_version": "fixture-contract",
            }
        },
        "embedder_kind": "sentence_transformers",
        "model_file_evidence": {
            "file_count": 1,
            "files": [{"path": "model.safetensors", "sha256": "e" * 64}],
            "revision": PINNED_MODEL_REVISION,
        },
        "real_inference": True,
        "truncation": {
            "applied": True,
            "max_seq_length": 512,
            "max_tokens": 512,
            "tokenizer_model_max_length": 512,
        },
        "truncation_satisfies_contract": True,
    }
    inference_digest = content_sha256(canonical_json_dumps(inference))
    checkpoint = {
        "config": config.to_dict(),
        "config_digest": config.digest,
        "inference": inference,
        "jurisdiction_code": jurisdiction,
        "parts": [
            {
                "descriptor": descriptor.to_dict(),
                "document_index_start": 0,
                "inference_digest": inference_digest,
                "input_digest": ("1" if jurisdiction == "CA" else "2") * 64,
                "part_index": 0,
                "row_count": len(rows),
                "sha256": descriptor.sha256,
            }
        ],
        "production_ready": True,
        "row_count": len(rows),
        "schema_version": EMBEDDING_STORE_SCHEMA_VERSION,
        "sort_receipt": {
            "family": "chunks",
            "interrupted": False,
            "max_records_in_memory": 2,
            "output_digest": "d" * 64,
            "output_path": "checkpoints/embedding_sort/chunks.sorted.jsonl",
            "peak_resident_records": 2,
            "records_consumed": len(rows),
            "row_count": len(rows),
            "run_count": 1,
            "schema_version": "hf-graphrag-external-sort/v1",
            "status": "complete",
        },
        "task_id": "fixture-production-embedding-store",
    }
    atomic_write_canonical_json(
        source_root / "checkpoints" / "embeddings" / f"{jurisdiction}.json",
        checkpoint,
    )
    return path


@pytest.fixture
def source_parts(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "embedding-store"
    ca = _write_source_part(source_root, "CA", [_unit(0), _unit(1)])
    tx = _write_source_part(source_root, "TX", [_unit(2), _unit(0, sign=-1.0)])
    return ca, tx


def _write(
    parts: tuple[Path, ...] | tuple[Path, Path],
    output: Path,
    **overrides: Any,
):
    options = {
        "kmeans_iterations": 2,
        "locator_page_size": 2,
        "max_centroids": 8,
        "max_rows_per_centroid": 1,
        "max_rows_per_shard": 1,
        "max_shards_per_centroid": 1,
        "max_sort_records_in_memory": 2,
        "max_training_rows": 4,
        "target_rows_per_centroid": 1,
    }
    options.update(overrides)
    return write_state_laws_vector_physical_layout(parts, output, **options)


def _read_descriptor(root: Path, value: Any) -> ArtifactDescriptor:
    descriptor = ArtifactDescriptor.from_mapping(value)
    verify_descriptor(root, descriptor)
    return descriptor


def test_writes_global_offsets_direct_columns_and_manifest_contract(
    tmp_path: Path, source_parts: tuple[Path, Path]
) -> None:
    output = tmp_path / "release"
    result = _write(source_parts, output)

    assert result.row_count == 4
    assert result.executed_part_count == 2
    assert result.resumed_part_count == 0
    assert result.parent_entry_cids == (
        "parent-ca-a",
        "parent-ca-b",
        "parent-tx-a",
        "parent-tx-b",
    )
    assert result.key_evidence["parent_entry_cids"] == result.parent_entry_cids

    cluster_ids = [int(row["cluster_id"]) for row in result.routing_rows]
    shard_ids = [int(row["shard_id"]) for row in result.routing_rows]
    assert sorted(set(cluster_ids)) == list(range(result.cluster_count))
    assert sorted(shard_ids) == list(range(result.shard_count))
    ca_clusters = {
        int(row["cluster_id"])
        for row in result.routing_rows
        if row["jurisdiction_code"] == "CA"
    }
    tx_clusters = {
        int(row["cluster_id"])
        for row in result.routing_rows
        if row["jurisdiction_code"] == "TX"
    }
    assert ca_clusters.isdisjoint(tx_clusters)
    assert all(
        f"jurisdiction={row['jurisdiction_code']}" in str(row["relative_path"])
        for row in result.routing_rows
    )

    data_rows: list[dict[str, Any]] = []
    for value in result.vector_data_descriptors:
        descriptor = _read_descriptor(output, value)
        table = pq.read_table(output / descriptor.relative_path)
        assert "record_json" not in table.column_names
        assert {
            "chunk_in_cluster",
            "cluster_id",
            "document_index",
            "embedding",
            "entry_cid",
            "schema_version",
        }.issubset(table.column_names)
        data_rows.extend(table.to_pylist())
    assert sorted(int(row["document_index"]) for row in data_rows) == [0, 1, 2, 3]
    assert all(len(row["embedding"]) == PINNED_DIMENSION for row in data_rows)

    for path in (VECTOR_INDEX_PATH, ENTRY_LOCATOR_INDEX_PATH):
        table = pq.read_table(output / path)
        assert table.num_rows > 0
        assert "record_json" not in table.column_names
    locator_keys = [
        str(row["entry_cid"])
        for descriptor_value in result.locator_page_descriptors
        for row in pq.read_table(
            output / str(descriptor_value["relative_path"])
        ).to_pylist()
    ]
    assert locator_keys == sorted(row["entry_cid"] for row in data_rows)
    assert sorted(result.iter_document_chunk_keys()) == sorted(
        (int(row["document_index"]), str(row["entry_cid"])) for row in data_rows
    )
    assert not Path(str(result.sort_receipt["output_path"])).is_absolute()

    fragment = result.to_manifest_fragment()
    assert set(fragment["indexes"]) == {
        "vector_chunks",
        "vector_entry_locator",
    }
    assert fragment["key_evidence"] == result.key_evidence
    assert fragment["production_ready"] is True
    assert fragment["inference"]["real_inference"] is True
    assert {item["family"] for item in fragment["artifacts"]} == {
        "centroids",
        "locator_index",
        "vectors",
    }
    centroid = next(
        item for item in fragment["artifacts"] if item["family"] == "centroids"
    )
    assert centroid["relative_path"] == CENTROID_DATA_PATH
    _read_descriptor(output, centroid)
    centroid_table = pq.read_table(output / CENTROID_DATA_PATH)
    assert "record_json" not in centroid_table.column_names
    assert {
        "assignment",
        "centroid",
        "cluster_id",
        "dimension",
        "row_count",
        "shard_count",
    }.issubset(centroid_table.column_names)
    assert centroid_table.num_rows == result.cluster_count
    vector = fragment["vector"]
    assert vector["assignment"] == "deterministic_balanced_spherical_kmeans"
    assert vector["model_id"] == PINNED_MODEL_ID
    assert vector["model_revision"] == PINNED_MODEL_REVISION
    assert vector["dimension"] == PINNED_DIMENSION
    assert vector["pooling"] == "mean"
    assert vector["normalization"] == "l2"
    assert vector["production_ready"] is True
    assert vector["inference"]["real_inference"] is True
    assert vector["projection_embeddings"] is False


def test_state_query_round_trip_and_frontier_hydration(
    tmp_path: Path, source_parts: tuple[Path, Path]
) -> None:
    output = tmp_path / "release"
    result = _write(source_parts, output)
    fragment = result.to_manifest_fragment()
    manifest = {
        "indexes": fragment["indexes"],
        "primary_key": "entry_cid",
        "schema_version": "hf-graphrag-release/v1",
        "vector": fragment["vector"],
    }
    (output / "manifest.json").write_bytes(
        canonical_json_dumps(manifest).encode("utf-8")
    )
    resolver = ImmutableHubResolver(
        repo_id="fixture/state-laws-vectors",
        revision=PINNED_RELEASE_REVISION,
        cache_dir=tmp_path / "cache",
        transport=LocalRootTransport(output),
        local_root=output,
        supported_schemas={"hf-graphrag-release/v1"},
    )
    client = StateLawsQueryClient(
        resolver,
        limits=QueryLimits(
            max_bytes=20_000_000,
            max_shards=32,
            max_rows=1_000,
            max_nodes=64,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )

    dense = client.engine.run_vector(
        _unit(0), candidate_centroids=1, hydrate=False, top_k=2
    )
    assert dense.complete is True
    assert dense.results[0]["entry_cid"] == "chunk-ca-a"
    hydrated = client.fetch_frontier_vectors(
        ["chunk-tx-b"], query_vector=_unit(0), candidate_centroids=1
    )
    assert hydrated["chunk-tx-b"] == pytest.approx(tuple(_unit(0, sign=-1.0)))
    assert any(
        "indexes/vector_entry_locator/part-" in item["relative_path"]
        for item in client.engine.fetch_trace()["files"]
    )


def test_resume_is_noop_and_rejects_input_and_output_drift(
    tmp_path: Path, source_parts: tuple[Path, Path]
) -> None:
    output = tmp_path / "release"
    first = _write(source_parts, output)
    checkpoint = output / "checkpoints/vector_physical.json"
    checkpoint_bytes = checkpoint.read_bytes()
    second = _write(source_parts, output)
    assert second.build_digest == first.build_digest
    assert second.executed_part_count == 0
    assert second.resumed_part_count == 2
    assert checkpoint.read_bytes() == checkpoint_bytes

    vector_path = output / str(first.vector_data_descriptors[0]["relative_path"])
    table = pq.read_table(vector_path)
    rows = table.to_pylist()
    rows[0]["entry_cid"] = "drifted-vector-key"
    pq.write_table(pa.Table.from_pylist(rows), vector_path, compression="zstd")
    with pytest.raises(StateLawsVectorOutputDriftError):
        _write(source_parts, output)

    other_output = tmp_path / "other-release"
    _write(source_parts, other_output)
    source_table = pq.read_table(source_parts[0])
    source_rows = source_table.to_pylist()
    source_rows[0]["input_hash"] = "f" * 64
    pq.write_table(
        pa.Table.from_pylist(source_rows), source_parts[0], compression="zstd"
    )
    with pytest.raises(StateLawsVectorInputDriftError):
        _write(source_parts, other_output)


def test_rejects_projection_or_unproved_inference(
    tmp_path: Path, source_parts: tuple[Path, Path]
) -> None:
    checkpoint = source_parts[0].parents[2] / "checkpoints/embeddings/CA.json"
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["production_ready"] = False
    atomic_write_canonical_json(checkpoint, payload)
    with pytest.raises(ProjectionEmbeddingRejectedError):
        _write(source_parts, tmp_path / "release")
