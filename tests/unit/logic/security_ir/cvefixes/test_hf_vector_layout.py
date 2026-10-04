"""Tests for remotely routable CVEfixes Hugging Face vector shards."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import (
    canonical_identity,
    cid_v1_from_digest,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_release import (
    HF_META_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_vector_layout import (
    CVEfixesHFVectorIntegrityError,
    CVEfixesHFVectorLayoutError,
    CVEFIXES_HF_VECTOR_CHUNK_SCHEMA_VERSION,
    VECTOR_DATA_COLUMNS,
    VECTOR_META_COLUMNS,
    build_cvefixes_hf_vector_layout,
    read_cvefixes_vector_meta_index,
    route_cvefixes_vector_shards,
    verify_cvefixes_vector_shard,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.retrieval import (
    NO_EMBEDDING_MODEL,
    RetrievalAuthority,
    RetrievalEntry,
    RetrievalIndex,
    RetrievalShard,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="vector-layout-test", schema_version="test/v1"
    ).cid


def _index(
    embeddings: tuple[tuple[float, ...], ...],
    *,
    revision: str = "a" * 40,
) -> RetrievalIndex:
    shard_id = "train:all"
    source_cid = _cid("source")
    entries = tuple(
        RetrievalEntry(
            node_cid=_cid(f"node-{position}"),
            partition="train",
            shard_key=shard_id,
            kind="code_unit",
            text=f"security record {position}",
            source_cids=(source_cid,),
            authority=RetrievalAuthority.NON_AUTHORITATIVE,
            embedding=embedding,
        )
        for position, embedding in enumerate(embeddings)
    )
    has_embeddings = any(embeddings)
    return RetrievalIndex(
        graph_root=_cid("graph"),
        graph_config_cid=_cid("graph-config"),
        retrieval_config_cid=_cid("retrieval-config"),
        model_id=(
            "sentence-transformers/all-MiniLM-L6-v2"
            if has_embeddings
            else NO_EMBEDDING_MODEL
        ),
        model_revision=revision if has_embeddings else NO_EMBEDDING_MODEL,
        model_config_cid=_cid("model-config"),
        shards=(
            RetrievalShard(
                shard_id=shard_id,
                partition="train",
                entries=entries,
            ),
        ),
    )


def _semantic_index(*, revision: str = "a" * 40) -> RetrievalIndex:
    return _index(
        (
            (1.0, 0.0),
            (0.95, 0.05),
            (0.8, 0.2),
            (-1.0, 0.0),
            (-0.95, 0.05),
            (-0.8, 0.2),
        ),
        revision=revision,
    )


def test_builds_skillcenter_compatible_content_addressed_vector_layout(
    tmp_path: Path,
) -> None:
    index = _semantic_index()
    summary = build_cvefixes_hf_vector_layout(
        index,
        tmp_path,
        require_embeddings=True,
        max_rows_per_shard=2,
        target_rows_per_centroid=3,
        max_centroids=8,
    )

    assert summary.vector_rows == 6
    assert summary.embedded_rows == 6
    assert summary.neutral_rows == 0
    assert summary.dimension == 2
    assert summary.cluster_count == 2
    assert summary.searchable_cluster_count == 2
    assert summary.vector_chunks == 4
    assert summary.model_name == (
        f"sentence-transformers/all-MiniLM-L6-v2@{'a' * 40}"
    )
    assert summary.manifest_config["searchable"] is True
    assert summary.manifest_config["retrieval_index_root"] == index.index_root

    meta_path = tmp_path / "indexes" / "vector_chunks.parquet"
    meta_file = pq.ParquetFile(meta_path)
    assert tuple(meta_file.schema_arrow.names) == VECTOR_META_COLUMNS
    assert meta_file.schema_arrow.metadata == {
        b"schema_version": HF_META_SCHEMA_VERSION.encode()
    }
    rows = read_cvefixes_vector_meta_index(meta_path)
    assert len(rows) == 4
    assert [row["shard_id"] for row in rows] == [0, 1, 2, 3]
    assert {row["dimension"] for row in rows} == {2}
    assert {row["model_name"] for row in rows} == {summary.model_name}

    observed_entry_cids: set[str] = set()
    observed_documents: list[int] = []
    for row in rows:
        shard_path = verify_cvefixes_vector_shard(tmp_path, row)
        content = shard_path.read_bytes()
        digest = hashlib.sha256(content).digest()
        assert row["sha256"] == digest.hex()
        assert row["cid"] == cid_v1_from_digest(digest)
        assert row["size_bytes"] == len(content)
        table = pq.read_table(shard_path)
        assert tuple(table.column_names) == VECTOR_DATA_COLUMNS
        assert (
            table.schema.metadata[b"schema_version"]
            == CVEFIXES_HF_VECTOR_CHUNK_SCHEMA_VERSION.encode()
        )
        observed_entry_cids.update(table["entry_cid"].to_pylist())
        observed_documents.extend(table["document_index"].to_pylist())
        assert table["has_embedding"].to_pylist() == [True] * table.num_rows

    expected_entry_cids = {
        entry.entry_id
        for shard in index.shards
        for entry in shard.entries
    }
    assert observed_entry_cids == expected_entry_cids
    assert sorted(observed_documents) == list(range(6))


def test_thin_client_routes_centroids_before_fetching_shards(
    tmp_path: Path,
) -> None:
    index = _semantic_index()
    summary = build_cvefixes_hf_vector_layout(
        index,
        tmp_path,
        require_embeddings=True,
        max_rows_per_shard=2,
        target_rows_per_centroid=3,
        max_centroids=8,
    )
    rows = read_cvefixes_vector_meta_index(
        tmp_path / "indexes" / "vector_chunks.parquet"
    )
    routes = route_cvefixes_vector_shards(
        rows,
        (1.0, 0.0),
        candidate_centroids=1,
        max_shards=2,
        expected_model_name=summary.model_name,
    )

    assert len(routes) == 2
    assert len({route.cluster_id for route in routes}) == 1
    assert all(route.score > 0.8 for route in routes)
    routed_entries = {
        entry_cid
        for route in routes
        for entry_cid in pq.read_table(
            tmp_path / route.relative_path, columns=["entry_cid"]
        )["entry_cid"].to_pylist()
    }
    positive_entry_cids = {
        entry.entry_id
        for shard in index.shards
        for entry in shard.entries
        if entry.embedding[0] > 0
    }
    assert routed_entries == positive_entry_cids


def test_vector_layout_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    kwargs = {
        "require_embeddings": True,
        "max_rows_per_shard": 2,
        "target_rows_per_centroid": 3,
        "max_centroids": 8,
    }
    first_summary = build_cvefixes_hf_vector_layout(
        _semantic_index(), first, **kwargs
    )
    second_summary = build_cvefixes_hf_vector_layout(
        _semantic_index(), second, **kwargs
    )

    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*.parquet")
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*.parquet")
    }
    assert first_files == second_files
    assert first_summary.meta_index["sha256"] == second_summary.meta_index["sha256"]
    assert [
        row["sha256"] for row in first_summary.chunk_rows
    ] == [row["sha256"] for row in second_summary.chunk_rows]


def test_neutral_layout_is_explicit_and_not_semantically_routable(
    tmp_path: Path,
) -> None:
    index = _index(((), (), ()))
    summary = build_cvefixes_hf_vector_layout(
        index,
        tmp_path / "neutral",
        max_rows_per_shard=2,
        target_rows_per_centroid=2,
    )

    assert summary.dimension == 0
    assert summary.embedded_rows == 0
    assert summary.neutral_rows == 3
    assert summary.searchable is False
    assert summary.searchable_cluster_count == 0
    neutral_root = tmp_path / "neutral"
    rows = read_cvefixes_vector_meta_index(
        neutral_root / "indexes" / "vector_chunks.parquet"
    )
    assert all(row["centroid"] == [] for row in rows)
    tables = [
        pq.read_table(neutral_root / row["relative_path"]) for row in rows
    ]
    assert all(
        available is False
        for table in tables
        for available in table["has_embedding"].to_pylist()
    )
    assert all(
        vector == []
        for table in tables
        for vector in table["embedding"].to_pylist()
    )
    with pytest.raises(
        CVEfixesHFVectorLayoutError,
        match="not semantically searchable",
    ):
        route_cvefixes_vector_shards(rows, ())
    with pytest.raises(
        CVEfixesHFVectorLayoutError,
        match="requires an embedding for every row",
    ):
        build_cvefixes_hf_vector_layout(
            index,
            tmp_path / "production",
            require_embeddings=True,
        )


def test_production_requires_immutable_model_revision(
    tmp_path: Path,
) -> None:
    moving_revision = _semantic_index(revision="main")
    with pytest.raises(
        CVEfixesHFVectorLayoutError,
        match="immutable model revision",
    ):
        build_cvefixes_hf_vector_layout(
            moving_revision,
            tmp_path / "rejected",
            require_embeddings=True,
        )

    summary = build_cvefixes_hf_vector_layout(
        moving_revision,
        tmp_path / "externally-pinned",
        require_embeddings=True,
        require_immutable_model_revision=False,
    )
    assert summary.embedded_rows == summary.vector_rows


def test_tampered_vector_shard_fails_descriptor_verification(
    tmp_path: Path,
) -> None:
    build_cvefixes_hf_vector_layout(
        _semantic_index(),
        tmp_path,
        require_embeddings=True,
        max_rows_per_shard=2,
        target_rows_per_centroid=3,
        max_centroids=8,
    )
    row = read_cvefixes_vector_meta_index(
        tmp_path / "indexes" / "vector_chunks.parquet"
    )[0]
    shard_path = tmp_path / row["relative_path"]
    shard_path.write_bytes(shard_path.read_bytes() + b"tampered")

    with pytest.raises(
        CVEfixesHFVectorIntegrityError,
        match="differs",
    ):
        verify_cvefixes_vector_shard(tmp_path, row)
