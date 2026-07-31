from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.ops.security_ir.query_cvefixes_security_ir import (
    ArtifactResolver,
    BM25_TOKENIZER,
    CVEfixesRemoteIndex,
    META_SCHEMA_VERSION,
    RemoteQueryError,
    _bound_model_name,
    _embedding_model_binding,
    _parser,
    _raw_sha256_cid,
    _read_query_vector,
)


REVISION = "a" * 40
MODEL_REVISION = "b" * 40
MODEL_CONFIG_CID = _raw_sha256_cid(hashlib.sha256(b"model config").digest())


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def _descriptor(
    path: Path,
    root: Path,
    *,
    row_count: int,
) -> dict[str, object]:
    content = path.read_bytes()
    digest = hashlib.sha256(content).digest()
    return {
        "cid": _raw_sha256_cid(digest),
        "relative_path": path.relative_to(root).as_posix(),
        "row_count": row_count,
        "sha256": digest.hex(),
        "size_bytes": len(content),
    }


def _meta_row(
    path: Path,
    root: Path,
    *,
    shard_id: int,
    row_count: int,
    first_key: str,
    last_key: str,
    kind: str,
    start_document_index: int = -1,
    end_document_index: int = -1,
    **extra: object,
) -> dict[str, object]:
    return {
        **_descriptor(path, root, row_count=row_count),
        "end_document_index": end_document_index,
        "first_key": first_key,
        "kind": kind,
        "last_key": last_key,
        "schema_version": META_SCHEMA_VERSION,
        "shard_id": shard_id,
        "start_document_index": start_document_index,
        **extra,
    }


def _write_index(
    root: Path,
    name: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    path = root / "indexes" / f"{name}.parquet"
    _write_parquet(path, rows)
    return _descriptor(path, root, row_count=len(rows))


def _build_release(root: Path) -> None:
    corpus_path = root / "data/corpus/part-000000.parquet"
    corpus_rows = [
        {
            "authority": "context_only",
            "document_index": 0,
            "entry_cid": "entry-a",
            "kind": "security_ir",
            "node_cid": "node-a",
            "schema_version": "cvefixes-hf-corpus/v1",
            "text": "buffer overflow in parser",
            "title": "CVE overflow repair",
        },
        {
            "authority": "context_only",
            "document_index": 1,
            "entry_cid": "entry-b",
            "kind": "security_ir",
            "node_cid": "node-b",
            "schema_version": "cvefixes-hf-corpus/v1",
            "text": "sanitize an untrusted path",
            "title": "CVE path repair",
        },
    ]
    _write_parquet(corpus_path, corpus_rows)

    posting_path = root / "data/bm25/postings/part-000000.parquet"
    posting_rows = [
        {
            "body_frequencies": [1],
            "corpus_frequency": 1,
            "document_frequency": 1,
            "document_indices": [0],
            "document_lengths": [5],
            "idf": 0.7,
            "posting_chunk_count": 1,
            "posting_chunk_index": 0,
            "schema_version": "cvefixes-hf-bm25-posting/v1",
            "term": "overflow",
            "title_frequencies": [1],
        },
        {
            "body_frequencies": [1],
            "corpus_frequency": 1,
            "document_frequency": 1,
            "document_indices": [1],
            "document_lengths": [5],
            "idf": 0.7,
            "posting_chunk_count": 1,
            "posting_chunk_index": 0,
            "schema_version": "cvefixes-hf-bm25-posting/v1",
            "term": "sanitize",
            "title_frequencies": [1],
        },
    ]
    _write_parquet(posting_path, posting_rows)

    vector_rows = (
        (
            root / "data/vectors/part-000000.parquet",
            {
                "chunk_id": "vector-000000",
                "cluster_id": 0,
                "document_index": 0,
                "embedding": [1.0, 0.0],
                "entry_cid": "entry-a",
                "has_embedding": True,
                "model_config_cid": MODEL_CONFIG_CID,
                "model_id": "test/model",
                "model_revision": MODEL_REVISION,
                "schema_version": "cvefixes-hf-vector/v1",
            },
        ),
        (
            root / "data/vectors/part-000001.parquet",
            {
                "chunk_id": "vector-000001",
                "cluster_id": 1,
                "document_index": 1,
                "embedding": [0.0, 1.0],
                "entry_cid": "entry-b",
                "has_embedding": True,
                "model_config_cid": MODEL_CONFIG_CID,
                "model_id": "test/model",
                "model_revision": MODEL_REVISION,
                "schema_version": "cvefixes-hf-vector/v1",
            },
        ),
    )
    for path, row in vector_rows:
        _write_parquet(path, [row])

    node_path = root / "data/graph/nodes/part-000000.parquet"
    node_rows = [
        {
            "entry_cid": "entry-a",
            "label": "A",
            "node_cid": "node-a",
            "node_type": "CVE",
            "properties_json": "{}",
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
        {
            "entry_cid": "entry-b",
            "label": "B",
            "node_cid": "node-b",
            "node_type": "FUNCTION",
            "properties_json": "{}",
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
        {
            "entry_cid": "entry-b",
            "label": "C",
            "node_cid": "node-c",
            "node_type": "POLICY",
            "properties_json": "{}",
            "schema_version": "cvefixes-hf-graph-node/v1",
        },
    ]
    _write_parquet(node_path, node_rows)

    adjacency_path = (
        root / "data/graph/adjacency/outgoing/part-000000.parquet"
    )
    adjacency_rows = [
        {
            "direction": "outgoing",
            "edge_cids": ["edge-ab", "edge-ac"],
            "edge_types": ["HAS_FUNCTION", "HAS_POLICY"],
            "neighbor_cids": ["node-b", "node-c"],
            "neighbor_count": 2,
            "neighbor_node_types": ["FUNCTION", "POLICY"],
            "node_cid": "node-a",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["deterministic_graph"] * 2,
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [1.0, 0.8],
            "total_neighbor_count": 2,
        },
        {
            "direction": "outgoing",
            "edge_cids": ["edge-bc"],
            "edge_types": ["IMPLEMENTS"],
            "neighbor_cids": ["node-c"],
            "neighbor_count": 1,
            "neighbor_node_types": ["POLICY"],
            "node_cid": "node-b",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": ["deterministic_graph"],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [0.9],
            "total_neighbor_count": 1,
        },
        {
            "direction": "outgoing",
            "edge_cids": [],
            "edge_types": [],
            "neighbor_cids": [],
            "neighbor_count": 0,
            "neighbor_node_types": [],
            "node_cid": "node-c",
            "page_count": 1,
            "page_index": 0,
            "retrieval_methods": [],
            "schema_version": "cvefixes-hf-graph-adjacency/v1",
            "scores": [],
            "total_neighbor_count": 0,
        },
    ]
    _write_parquet(adjacency_path, adjacency_rows)

    index_descriptors = {
        "corpus_chunks": _write_index(
            root,
            "corpus_chunks",
            [
                _meta_row(
                    corpus_path,
                    root,
                    shard_id=0,
                    row_count=2,
                    first_key="entry-a",
                    last_key="entry-b",
                    kind="corpus",
                    start_document_index=0,
                    end_document_index=1,
                )
            ],
        ),
        "bm25_keyword_shards": _write_index(
            root,
            "bm25_keyword_shards",
            [
                _meta_row(
                    posting_path,
                    root,
                    shard_id=0,
                    row_count=2,
                    first_key="overflow",
                    last_key="sanitize",
                    kind="bm25_postings",
                )
            ],
        ),
        "vector_chunks": _write_index(
            root,
            "vector_chunks",
            [
                _meta_row(
                    path,
                    root,
                    shard_id=index,
                    row_count=1,
                    first_key=f"entry-{'a' if index == 0 else 'b'}",
                    last_key=f"entry-{'a' if index == 0 else 'b'}",
                    kind="vectors",
                    start_document_index=index,
                    end_document_index=index,
                    centroid=(
                        [1.0, 0.0] if index == 0 else [0.0, 1.0]
                    ),
                    centroid_shard_count=1,
                    chunk_in_cluster=0,
                    cluster_id=index,
                    dimension=2,
                    model_name=f"test/model@{MODEL_REVISION}",
                    shard_centroid=(
                        [1.0, 0.0] if index == 0 else [0.0, 1.0]
                    ),
                )
                for index, (path, _) in enumerate(vector_rows)
            ],
        ),
        "graph_node_chunks": _write_index(
            root,
            "graph_node_chunks",
            [
                _meta_row(
                    node_path,
                    root,
                    shard_id=0,
                    row_count=3,
                    first_key="node-a",
                    last_key="node-c",
                    kind="graph_nodes",
                )
            ],
        ),
        "graph_outgoing_adjacency": _write_index(
            root,
            "graph_outgoing_adjacency",
            [
                _meta_row(
                    adjacency_path,
                    root,
                    shard_id=0,
                    row_count=3,
                    first_key="node-a",
                    last_key="node-c",
                    kind="graph_outgoing_adjacency",
                    adjacency_count=3,
                    direction="outgoing",
                    first_page_index=0,
                    last_page_index=0,
                    node_count=3,
                )
            ],
        ),
    }
    manifest = {
        "bm25": {
            "average_document_length": 5.0,
            "b": 0.75,
            "body_weight": 1.0,
            "k1": 1.2,
            "max_query_terms": 64,
            "title_weight": 5.0,
            "tokenizer": BM25_TOKENIZER,
        },
        "dataset_id": "Publicus/cvefixes-security-ir-graphrag",
        "indexes": index_descriptors,
        "primary_key": "entry_cid",
        "schema_version": "cvefixes-huggingface-release/v1",
        "vector": {
            "default_probe_centroids": 1,
            "dimension": 2,
            "layout": "semantic_centroid_groups",
            "max_shards_per_centroid": 2,
            "model_config_cid": MODEL_CONFIG_CID,
            "model_id": "test/model",
            "model_name": f"test/model@{MODEL_REVISION}",
            "model_revision": MODEL_REVISION,
            "neutral_rows": 0,
            "searchable": True,
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )


def _index(root: Path) -> CVEfixesRemoteIndex:
    return CVEfixesRemoteIndex(
        ArtifactResolver(
            repo_id="Publicus/test-cvefixes",
            revision=REVISION,
            cache_dir=root / ".cache",
            local_root=root,
        )
    )


def test_revision_must_be_an_immutable_hub_commit(tmp_path: Path) -> None:
    with pytest.raises(RemoteQueryError, match="immutable"):
        ArtifactResolver(
            repo_id="Publicus/test-cvefixes",
            revision="main",
            local_root=tmp_path,
        )


def test_schema_v1_implies_entry_cid_but_rejects_a_conflicting_key(
    tmp_path: Path,
) -> None:
    _build_release(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["primary_key"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert _index(tmp_path).bm25("overflow", top_k=1)["result_count"] == 1

    manifest["primary_key"] = "record_id"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RemoteQueryError, match="entry_cid"):
        _index(tmp_path)


def test_bm25_and_vector_use_integrity_checked_bounded_shards(
    tmp_path: Path,
) -> None:
    _build_release(tmp_path)

    bm25 = _index(tmp_path).bm25("buffer-overflow", top_k=1)
    assert bm25["hub_revision"] == REVISION
    assert bm25["results"][0]["entry_cid"] == "entry-a"
    assert bm25["results"][0]["matched_terms"] == ["overflow"]
    assert bm25["diagnostics"]["keyword_shards_fetched"] == 1
    assert {
        item["relative_path"] for item in bm25["fetch_trace"]["files"]
    } == {
        "data/bm25/postings/part-000000.parquet",
        "data/corpus/part-000000.parquet",
        "indexes/bm25_keyword_shards.parquet",
        "indexes/corpus_chunks.parquet",
        "manifest.json",
    }

    vector = _index(tmp_path).vector(
        "path repair",
        top_k=1,
        query_vector=[0.0, 1.0],
        candidate_centroids=1,
        max_vector_shards=1,
    )
    assert vector["results"][0]["entry_cid"] == "entry-b"
    assert vector["diagnostics"]["candidate_centroid_ids"] == [1]
    assert vector["diagnostics"]["vector_shards_fetched"] == 1
    assert "data/vectors/part-000000.parquet" not in {
        item["relative_path"] for item in vector["fetch_trace"]["files"]
    }


def test_no_content_removes_corpus_text(tmp_path: Path) -> None:
    _build_release(tmp_path)
    result = _index(tmp_path).bm25(
        "overflow", top_k=1, include_content=False
    )
    assert "text" not in result["results"][0]
    assert result["results"][0]["title"] == "CVE overflow repair"


def test_graph_walk_obeys_node_edge_and_shard_budgets(tmp_path: Path) -> None:
    _build_release(tmp_path)
    index = _index(tmp_path)

    neighbors = index.graph_neighbors(
        "node-a",
        direction="outgoing",
        limit=1,
        max_shards=1,
    )
    assert [row["neighbor_cid"] for row in neighbors["results"]] == ["node-b"]
    assert neighbors["diagnostics"]["adjacency_shards_fetched"] == 1

    walk = index.graph_walk(
        "node-a",
        direction="outgoing",
        max_depth=2,
        max_nodes=2,
        max_edges=10,
        per_node_limit=4,
        max_shards=1,
    )
    assert walk["diagnostics"]["stop_reason"] == "max_nodes"
    assert {row["node_cid"] for row in walk["nodes"]} == {"node-a", "node-b"}
    assert len(walk["edges"]) == 1
    assert {
        walk["edges"][0]["source_cid"],
        walk["edges"][0]["target_cid"],
    } <= {"node-a", "node-b"}


def test_raw_file_cid_is_checked_before_meta_index_use(tmp_path: Path) -> None:
    _build_release(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wrong_digest = hashlib.sha256(b"wrong artifact").digest()
    manifest["indexes"]["bm25_keyword_shards"]["cid"] = _raw_sha256_cid(
        wrong_digest
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RemoteQueryError, match="CID differs"):
        _index(tmp_path).bm25("overflow", top_k=1)


def test_declared_shard_key_range_is_checked_against_parquet(
    tmp_path: Path,
) -> None:
    _build_release(tmp_path)
    index_path = tmp_path / "indexes/bm25_keyword_shards.parquet"
    rows = pq.read_table(index_path).to_pylist()
    rows[0]["first_key"] = "aardvark"
    _write_parquet(index_path, rows)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["indexes"]["bm25_keyword_shards"] = _descriptor(
        index_path, tmp_path, row_count=1
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RemoteQueryError, match="key range differs"):
        _index(tmp_path).bm25("overflow", top_k=1)


def test_cli_defaults_to_cuda_and_enforces_manifest_model_binding() -> None:
    parser = _parser()
    assert "--token" not in parser.format_help()
    args = parser.parse_args(
        [
            "--revision",
            REVISION,
            "vector",
            "overflow",
            "--query-vector-json",
            "[1.0, 0.0]",
        ]
    )
    assert args.device == "cuda"
    model_name = f"test/model@{MODEL_REVISION}"
    manifest = {
        "vector": {
            "model_id": "test/model",
            "model_name": model_name,
            "model_revision": MODEL_REVISION,
        }
    }
    assert _bound_model_name(manifest, model_name) == model_name
    assert _embedding_model_binding(manifest, model_name) == (
        model_name,
        "test/model",
        MODEL_REVISION,
    )
    with pytest.raises(RemoteQueryError, match="exactly match"):
        _bound_model_name(manifest, "different/model")


def test_query_vector_accepts_long_inline_json_without_path_probe() -> None:
    expected = [index / 383.0 for index in range(384)]
    inline = json.dumps(expected)
    assert len(inline) > 255

    assert _read_query_vector(inline) == expected


def test_query_vector_still_accepts_json_file_path(tmp_path: Path) -> None:
    path = tmp_path / "query-vector.json"
    path.write_text("[1.0, -2.5, 3.25]", encoding="utf-8")

    assert _read_query_vector(str(path)) == [1.0, -2.5, 3.25]
