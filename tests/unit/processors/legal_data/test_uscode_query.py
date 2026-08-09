"""Unit tests for legal hybrid and embedding-guided graph queries (USCIR-027).

Acceptance:

* Hybrid explanations preserve component scores.
* Graph walks enforce all budgets.
* Off-centroid frontier vectors are selectively fetched.
* Similarity edges are never presented as legal authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.uscode_query import (
    FIXTURE_SCHEMA_VERSION,
    FUSION_METHODS,
    GOAL_ID,
    SCHEMA_VERSION,
    TASK_ID,
    FusionConfig,
    LegalAuthorityCollisionError,
    LegalFilters,
    SemanticBeamConfig,
    UscodeQueryClient,
    annotate_edge_authority,
    assert_no_similarity_as_legal_authority,
    build_default_uscode_query_expected_fixture_payload,
    classify_edge_authority,
    cosine_similarity,
    default_uscode_query_expected_fixture_path,
    fuse_hybrid_results,
    graph_walk,
    hybrid_search,
    is_similarity_edge_type,
    load_uscode_query_expected_fixture,
    query_replay_fingerprint,
    select_vector_shards_for_keys,
    semantic_graph_walk,
    similarity_edge_semantics,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    BUDGET_DIMENSIONS,
    QueryLimits,
    ROUTE_FAMILIES,
    ROUTE_REASONS,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import ModelSpace
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
    build_descriptor_for_bytes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_dumps,
)

PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
REPO_ID = "justicedao/ipfs_uscode"
FIXTURE_PATH = default_uscode_query_expected_fixture_path()
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f19aa49b8566f3e3"
MODEL_ID = "fixture-unit-v1"
VECTOR_SPACE_ID = f"fixture-unit-v1@{MODEL_REVISION}:d2:norm=l2"


# ---------------------------------------------------------------------------
# Miniature offline release builder
# ---------------------------------------------------------------------------


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")
    return path.read_bytes()


def _desc(path: Path, root: Path, *, row_count: int) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    content = path.read_bytes()
    return build_descriptor_for_bytes(
        relative,
        content,
        row_count=row_count,
        media_type="application/vnd.apache.parquet",
        schema_id="hf-graphrag-release/v1",
    ).to_dict()


def build_mini_release(root: Path) -> dict[str, object]:
    """Build a descriptor-complete offline release for USCIR-027 tests.

    Graph layout (node CIDs align with vector entry keys for frontier fetch):

    * node-a (entry-a, centroid 0) --CONTAINS--> node-b (entry-b, centroid 1)
    * node-b --CITES--> node-c (entry-c, centroid 1)
    * node-a --BM25_NEIGHBOR_OF--> node-b  (similarity, non-authoritative)
    """

    # --- BM25 postings ---
    postings_a = [
        {
            "body_frequencies": [1, 1],
            "document_indices": [0, 1],
            "document_lengths": [10, 12],
            "entry_cids": ["entry-a", "entry-b"],
            "idf": 1.5,
            "term": "agency",
            "title_frequencies": [1, 0],
        },
        {
            "body_frequencies": [2],
            "document_indices": [0],
            "document_lengths": [10],
            "entry_cids": ["entry-a"],
            "idf": 2.0,
            "term": "foia",
            "title_frequencies": [1],
        },
    ]
    postings_b = [
        {
            "body_frequencies": [1],
            "document_indices": [1],
            "document_lengths": [12],
            "entry_cids": ["entry-b"],
            "idf": 1.2,
            "term": "privacy",
            "title_frequencies": [1],
        },
    ]
    post_a_path = root / "data/bm25/postings/part-000000.parquet"
    post_b_path = root / "data/bm25/postings/part-000001.parquet"
    _write_parquet(post_a_path, postings_a)
    _write_parquet(post_b_path, postings_b)
    post_a_desc = _desc(post_a_path, root, row_count=2)
    post_b_desc = _desc(post_b_path, root, row_count=1)

    keyword_meta = [
        {
            **post_a_desc,
            "first_key": "agency",
            "kind": "bm25_postings",
            "last_key": "foia",
            "shard_id": 0,
        },
        {
            **post_b_desc,
            "first_key": "privacy",
            "kind": "bm25_postings",
            "last_key": "privacy",
            "shard_id": 1,
        },
    ]
    keyword_path = root / "indexes/bm25_keyword_shards.parquet"
    _write_parquet(keyword_path, keyword_meta)
    keyword_desc = _desc(keyword_path, root, row_count=2)

    # --- Corpus ---
    corpus_rows = [
        {
            "chapter": "5",
            "citation": "5 U.S.C. § 552",
            "document_index": 0,
            "entry_cid": "entry-a",
            "legal_id": "usc:us:5:552",
            "release_point": "2024-01",
            "section": "552",
            "source": "uscode",
            "text": "FOIA agency records",
            "title": "5",
            "version": "2024",
        },
        {
            "chapter": "5",
            "citation": "5 U.S.C. § 552a",
            "document_index": 1,
            "entry_cid": "entry-b",
            "legal_id": "usc:us:5:552a",
            "release_point": "2024-01",
            "section": "552a",
            "source": "uscode",
            "text": "Privacy Act agency disclosure",
            "title": "5",
            "version": "2024",
        },
        {
            "chapter": "35",
            "citation": "35 U.S.C. § 101",
            "document_index": 2,
            "entry_cid": "entry-c",
            "legal_id": "usc:us:35:101",
            "release_point": "2024-01",
            "section": "101",
            "source": "uscode",
            "text": "Patentable inventions",
            "title": "35",
            "version": "2023",
        },
    ]
    corpus_path = root / "data/corpus/part-000000.parquet"
    _write_parquet(corpus_path, corpus_rows)
    corpus_desc = _desc(corpus_path, root, row_count=3)
    corpus_meta = [
        {
            **corpus_desc,
            "end_document_index": 2,
            "first_key": "entry-a",
            "kind": "corpus",
            "last_key": "entry-c",
            "shard_id": 0,
            "start_document_index": 0,
        }
    ]
    corpus_index_path = root / "indexes/corpus_chunks.parquet"
    _write_parquet(corpus_index_path, corpus_meta)
    corpus_index_desc = _desc(corpus_index_path, root, row_count=1)

    # --- Vectors (two centroids; node-a on centroid 0, node-b/c on centroid 1)
    # Keys use node-* so semantic frontier fetch can resolve by node_cid.
    # entry_cid is also present for hybrid search hydration.
    vec_a = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 0,
            "document_index": 0,
            "embedding": [1.0, 0.0],
            "entry_cid": "node-a",
            "node_cid": "node-a",
        }
    ]
    vec_b = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 1,
            "document_index": 1,
            "embedding": [-1.0, 0.0],
            "entry_cid": "node-b",
            "node_cid": "node-b",
        },
        {
            "chunk_in_cluster": 1,
            "cluster_id": 1,
            "document_index": 2,
            "embedding": [-0.9, 0.1],
            "entry_cid": "node-c",
            "node_cid": "node-c",
        },
    ]
    # Also index entry-* vectors for hybrid BM25/vector fusion tests.
    vec_entry_a = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 0,
            "document_index": 0,
            "embedding": [1.0, 0.0],
            "entry_cid": "entry-a",
        }
    ]
    vec_entry_b = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 1,
            "document_index": 1,
            "embedding": [-1.0, 0.0],
            "entry_cid": "entry-b",
        }
    ]
    # Physical layout:
    #   centroid-0 holds entry-a AND node-a (same semantic lobe)
    #   centroid-1 holds entry-b, node-b, node-c
    vec_a_path = root / "data/vectors/centroid-000000-part-000000.parquet"
    vec_b_path = root / "data/vectors/centroid-000001-part-000000.parquet"
    _write_parquet(vec_a_path, vec_a + vec_entry_a)
    _write_parquet(vec_b_path, vec_b + vec_entry_b)
    vec_a_desc = _desc(vec_a_path, root, row_count=2)
    vec_b_desc = _desc(vec_b_path, root, row_count=3)

    # first_key/last_key cover both entry-* and node-* for direct CID locate.
    # entry-a < entry-b < node-a < node-b < node-c lexicographically?
    # "entry-a" < "entry-b" < "node-a" < "node-b" < "node-c"  (e < n)
    # But entry-a and node-a are on different... wait, both on centroid 0.
    # entry-b, node-b, node-c on centroid 1.
    # Lexicographic ranges:
    #   centroid-0: entry-a ... node-a  (covers entry-a and node-a)
    #   centroid-1: entry-b ... node-c  (covers entry-b, node-b, node-c)
    # But entry-b is between entry-a and node-a! So ranges would overlap badly.
    #
    # Fix: use only node-* as primary keys in vector index for graph, and
    # separate entry keys carefully. Better approach: put entry vectors in
    # shards keyed by entry, and node vectors keyed by node, with non-
    # overlapping ranges.
    #
    # Simpler fix for tests:
    #   shard 0: first_key=entry-a, last_key=entry-a  (only entry-a)
    #   shard 1: first_key=entry-b, last_key=entry-b  (only entry-b)
    #   And for graph frontier, use entry CIDs as node CIDs in the graph!
    # That way one identity space works for hybrid + graph.

    # Rebuild with unified identity: graph nodes = entry CIDs.
    return _build_unified_release(root)


def _build_unified_release(root: Path) -> dict[str, object]:
    """Rebuild mini release with graph nodes == entry CIDs for frontier fetch."""

    # Clean and rewrite everything under root.
    # BM25
    postings_a = [
        {
            "body_frequencies": [1, 1],
            "document_indices": [0, 1],
            "document_lengths": [10, 12],
            "entry_cids": ["entry-a", "entry-b"],
            "idf": 1.5,
            "term": "agency",
            "title_frequencies": [1, 0],
        },
        {
            "body_frequencies": [2],
            "document_indices": [0],
            "document_lengths": [10],
            "entry_cids": ["entry-a"],
            "idf": 2.0,
            "term": "foia",
            "title_frequencies": [1],
        },
    ]
    postings_b = [
        {
            "body_frequencies": [1],
            "document_indices": [1],
            "document_lengths": [12],
            "entry_cids": ["entry-b"],
            "idf": 1.2,
            "term": "privacy",
            "title_frequencies": [1],
        },
    ]
    post_a_path = root / "data/bm25/postings/part-000000.parquet"
    post_b_path = root / "data/bm25/postings/part-000001.parquet"
    _write_parquet(post_a_path, postings_a)
    _write_parquet(post_b_path, postings_b)
    post_a_desc = _desc(post_a_path, root, row_count=2)
    post_b_desc = _desc(post_b_path, root, row_count=1)
    keyword_meta = [
        {
            **post_a_desc,
            "first_key": "agency",
            "kind": "bm25_postings",
            "last_key": "foia",
            "shard_id": 0,
        },
        {
            **post_b_desc,
            "first_key": "privacy",
            "kind": "bm25_postings",
            "last_key": "privacy",
            "shard_id": 1,
        },
    ]
    keyword_path = root / "indexes/bm25_keyword_shards.parquet"
    _write_parquet(keyword_path, keyword_meta)
    keyword_desc = _desc(keyword_path, root, row_count=2)

    corpus_rows = [
        {
            "chapter": "5",
            "citation": "5 U.S.C. § 552",
            "document_index": 0,
            "entry_cid": "entry-a",
            "legal_id": "usc:us:5:552",
            "release_point": "2024-01",
            "section": "552",
            "source": "uscode",
            "text": "FOIA agency records",
            "title": "5",
            "version": "2024",
        },
        {
            "chapter": "5",
            "citation": "5 U.S.C. § 552a",
            "document_index": 1,
            "entry_cid": "entry-b",
            "legal_id": "usc:us:5:552a",
            "release_point": "2024-01",
            "section": "552a",
            "source": "uscode",
            "text": "Privacy Act agency disclosure",
            "title": "5",
            "version": "2024",
        },
        {
            "chapter": "35",
            "citation": "35 U.S.C. § 101",
            "document_index": 2,
            "entry_cid": "entry-c",
            "legal_id": "usc:us:35:101",
            "release_point": "2024-01",
            "section": "101",
            "source": "uscode",
            "text": "Patentable inventions",
            "title": "35",
            "version": "2023",
        },
    ]
    corpus_path = root / "data/corpus/part-000000.parquet"
    _write_parquet(corpus_path, corpus_rows)
    corpus_desc = _desc(corpus_path, root, row_count=3)
    corpus_meta = [
        {
            **corpus_desc,
            "end_document_index": 2,
            "first_key": "entry-a",
            "kind": "corpus",
            "last_key": "entry-c",
            "shard_id": 0,
            "start_document_index": 0,
        }
    ]
    corpus_index_path = root / "indexes/corpus_chunks.parquet"
    _write_parquet(corpus_index_path, corpus_meta)
    corpus_index_desc = _desc(corpus_index_path, root, row_count=1)

    # Vectors: centroid 0 = entry-a; centroid 1 = entry-b + entry-c
    # Query [1,0] selects centroid 0 only → entry-b/c are off-centroid.
    vec_a = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 0,
            "document_index": 0,
            "embedding": [1.0, 0.0],
            "entry_cid": "entry-a",
        }
    ]
    vec_b = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 1,
            "document_index": 1,
            "embedding": [-1.0, 0.0],
            "entry_cid": "entry-b",
        },
        {
            "chunk_in_cluster": 1,
            "cluster_id": 1,
            "document_index": 2,
            "embedding": [-0.8, 0.2],
            "entry_cid": "entry-c",
        },
    ]
    vec_a_path = root / "data/vectors/centroid-000000-part-000000.parquet"
    vec_b_path = root / "data/vectors/centroid-000001-part-000000.parquet"
    _write_parquet(vec_a_path, vec_a)
    _write_parquet(vec_b_path, vec_b)
    vec_a_desc = _desc(vec_a_path, root, row_count=1)
    vec_b_desc = _desc(vec_b_path, root, row_count=2)
    vector_meta = [
        {
            **vec_a_desc,
            "centroid": [1.0, 0.0],
            "centroid_max_score": 1.0,
            "centroid_min_score": 1.0,
            "centroid_shard_count": 1,
            "chunk_in_cluster": 0,
            "cluster_id": 0,
            "dimension": 2,
            "first_key": "entry-a",
            "kind": "vectors",
            "last_key": "entry-a",
            "shard_centroid": [1.0, 0.0],
            "shard_id": 0,
        },
        {
            **vec_b_desc,
            "centroid": [-1.0, 0.0],
            "centroid_max_score": 1.0,
            "centroid_min_score": 0.8,
            "centroid_shard_count": 1,
            "chunk_in_cluster": 0,
            "cluster_id": 1,
            "dimension": 2,
            "first_key": "entry-b",
            "kind": "vectors",
            "last_key": "entry-c",
            "shard_centroid": [-0.9, 0.1],
            "shard_id": 1,
        },
    ]
    vector_index_path = root / "indexes/vector_chunks.parquet"
    _write_parquet(vector_index_path, vector_meta)
    vector_index_desc = _desc(vector_index_path, root, row_count=2)

    # Graph: entry-a -CONTAINS-> entry-b -CITES-> entry-c
    #        entry-a -BM25_NEIGHBOR_OF-> entry-b  (similarity)
    adj_rows = [
        {
            "edge_cid": "edge-a-b-contains",
            "edge_type": "CONTAINS",
            "neighbor_cid": "entry-b",
            "node_cid": "entry-a",
            "score": 0.9,
        },
        {
            "edge_cid": "edge-a-b-neighbor",
            "edge_type": "BM25_NEIGHBOR_OF",
            "neighbor_cid": "entry-b",
            "node_cid": "entry-a",
            "score": 0.7,
        },
        {
            "edge_cid": "edge-b-c-cites",
            "edge_type": "CITES",
            "neighbor_cid": "entry-c",
            "node_cid": "entry-b",
            "score": 0.5,
        },
    ]
    adj_path = root / "data/graph/adjacency/out/part-000000.parquet"
    _write_parquet(adj_path, adj_rows)
    adj_desc = _desc(adj_path, root, row_count=3)
    adj_meta = [
        {
            **adj_desc,
            "first_key": "entry-a",
            "kind": "graph_adjacency_out",
            "last_key": "entry-c",
            "shard_id": 0,
        }
    ]
    adj_index_path = root / "indexes/graph_out_adjacency.parquet"
    _write_parquet(adj_index_path, adj_meta)
    adj_index_desc = _desc(adj_index_path, root, row_count=1)

    manifest = {
        "bm25": {
            "average_document_length": 11.0,
            "b": 0.75,
            "body_weight": 1.0,
            "k1": 1.2,
            "title_weight": 5.0,
            "tokenizer": "hf-graphrag-bm25-tokens/v1",
        },
        "indexes": {
            "bm25_keyword_shards": keyword_desc,
            "corpus_chunks": corpus_index_desc,
            "graph_out_adjacency": adj_index_desc,
            "vector_chunks": vector_index_desc,
        },
        "primary_key": "entry_cid",
        "schema_version": "hf-graphrag-release/v1",
        "vector": {
            "default_probe_centroids": 1,
            "dimension": 2,
            "layout": "semantic_centroid_groups",
            "max_shards_per_centroid": 1,
            "model_id": MODEL_ID,
            "model_name": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "normalization": "l2",
            "vector_space_id": VECTOR_SPACE_ID,
        },
    }
    (root / "manifest.json").write_bytes(
        canonical_json_dumps(manifest).encode("utf-8")
    )
    return manifest


def _client(
    tmp_path: Path,
    *,
    limits: QueryLimits | None = None,
) -> UscodeQueryClient:
    release = tmp_path / "release"
    release.mkdir(parents=True, exist_ok=True)
    build_mini_release(release)
    resolver = ImmutableHubResolver(
        repo_id=REPO_ID,
        revision=PINNED_REVISION,
        cache_dir=tmp_path / "cache",
        transport=LocalRootTransport(release),
        local_root=release,
        supported_schemas={
            "hf-graphrag-release/v1",
            "publicus-ir-graphrag/v2",
        },
    )
    return UscodeQueryClient(
        resolver,
        limits=limits
        or QueryLimits(
            max_bytes=10_000_000,
            max_shards=32,
            max_rows=10_000,
            max_nodes=64,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )


def _release_space() -> ModelSpace:
    return ModelSpace(
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        vector_space_id=VECTOR_SPACE_ID,
        dimension=2,
        normalization="l2",
    )


def _trace_paths(result) -> set[str]:
    return {
        str(item.get("relative_path") or "")
        for item in (result.fetch_trace.get("files") or [])
    }


def _trace_vector_meta(result) -> list[dict[str, Any]]:
    rows = []
    for item in result.fetch_trace.get("files") or []:
        route = item.get("route") or {}
        if route.get("family") == "vectors":
            rows.append(dict(route.get("metadata") or {}))
    return rows


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_uscode_query_expected_fixture_is_sealed() -> None:
    assert FIXTURE_PATH.is_file()
    payload = load_uscode_query_expected_fixture(FIXTURE_PATH)
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["query_schema_version"] == SCHEMA_VERSION
    acceptance = payload["acceptance"]
    assert acceptance["hybrid_explanations_preserve_component_scores"] is True
    assert acceptance["graph_walks_enforce_all_budgets"] is True
    assert acceptance["off_centroid_frontier_vectors_selectively_fetched"] is True
    assert acceptance["similarity_edges_never_legal_authority"] is True
    generated = build_default_uscode_query_expected_fixture_payload()
    assert generated["schema_version"] == payload["schema_version"]
    assert generated["cases"] == payload["cases"]
    assert set(generated["route_families"]) == set(ROUTE_FAMILIES)
    assert set(generated["route_reasons"]) == set(ROUTE_REASONS)
    assert set(generated["bounds"]["budget_dimensions"]) == set(
        BUDGET_DIMENSIONS
    )
    assert set(generated["bounds"]["fusion_methods"]) == set(FUSION_METHODS)


def test_fixture_payload_is_deterministic() -> None:
    first = build_default_uscode_query_expected_fixture_payload()
    second = build_default_uscode_query_expected_fixture_payload()
    assert first == second
    assert canonical_json_dumps(first) == canonical_json_dumps(second)


# ---------------------------------------------------------------------------
# Authority: similarity never legal authority
# ---------------------------------------------------------------------------


def test_similarity_edge_classification_is_non_authoritative() -> None:
    for edge_type in ("BM25_NEIGHBOR_OF", "SIMILAR_TO"):
        assert is_similarity_edge_type(edge_type) is True
        classified = classify_edge_authority(edge_type)
        assert classified["legal_authority"] is False
        assert classified["proof_authority"] is False
        assert classified["authority"] == "non_authoritative"
        assert classified["retrieval_hint"] is True
        assert classified["edge_class"] == "similarity"

    legal = classify_edge_authority("CITES")
    assert legal["legal_authority"] is True
    assert legal["edge_class"] == "citation"

    semantics = similarity_edge_semantics()
    assert semantics["legal_authority"] is False
    assert semantics["proof_authority"] is False


def test_similarity_edge_cannot_claim_legal_authority() -> None:
    with pytest.raises(LegalAuthorityCollisionError):
        annotate_edge_authority(
            {
                "edge_type": "BM25_NEIGHBOR_OF",
                "legal_authority": True,
                "neighbor_cid": "entry-b",
            }
        )
    with pytest.raises(LegalAuthorityCollisionError):
        annotate_edge_authority(
            {
                "edge_type": "SIMILAR_TO",
                "authority": "legal",
                "neighbor_cid": "entry-b",
            }
        )
    with pytest.raises(LegalAuthorityCollisionError):
        assert_no_similarity_as_legal_authority(
            [
                {
                    "edge_type": "BM25_NEIGHBOR_OF",
                    "legal_authority": True,
                    "authority": "legal",
                    "proof_authority": True,
                    "edge_class": "authority",
                }
            ]
        )


def test_neighbors_labels_similarity_as_non_authoritative(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    result = client.neighbors("entry-a", direction="out", limit=10)
    assert result.mode == "neighbors"
    assert result.edges
    sim_edges = [
        edge
        for edge in result.edges
        if edge.get("edge_type") == "BM25_NEIGHBOR_OF"
    ]
    assert sim_edges, "expected a BM25_NEIGHBOR_OF edge in the mini release"
    for edge in sim_edges:
        assert edge["legal_authority"] is False
        assert edge["proof_authority"] is False
        assert edge["authority"] == "non_authoritative"
        assert edge["edge_class"] == "similarity"
        assert edge["retrieval_hint"] is True
    legal_edges = [
        edge for edge in result.edges if edge.get("edge_type") == "CONTAINS"
    ]
    assert legal_edges
    assert legal_edges[0]["legal_authority"] is True
    assert result.explain["similarity_never_legal_authority"] is True


# ---------------------------------------------------------------------------
# Hybrid fusion preserves component scores
# ---------------------------------------------------------------------------


def test_fuse_hybrid_results_preserves_component_scores() -> None:
    bm25 = [
        {"entry_cid": "entry-a", "score": 2.0, "normalized_score": 1.0},
        {"entry_cid": "entry-b", "score": 1.0, "normalized_score": 0.5},
    ]
    vector = [
        {"entry_cid": "entry-a", "score": 0.9, "normalized_score": 1.0},
        {"entry_cid": "entry-c", "score": 0.1, "normalized_score": 0.0},
    ]
    fused = fuse_hybrid_results(
        bm25,
        vector,
        config=FusionConfig(method="weighted", bm25_weight=0.5, vector_weight=0.5),
        top_k=5,
    )
    by_cid = {hit["entry_cid"]: hit for hit in fused}
    assert "entry-a" in by_cid
    hit = by_cid["entry-a"]
    assert hit["bm25_score"] == 1.0
    assert hit["vector_score"] == 1.0
    assert hit["component_scores"] == {"bm25": 1.0, "vector": 1.0}
    assert "score" in hit
    assert hit["fusion_method"] == "weighted"

    rrf = fuse_hybrid_results(
        bm25,
        vector,
        config=FusionConfig(method="rrf", rrf_k=60),
        top_k=5,
    )
    assert rrf[0]["component_scores"]["bm25"] >= 0.0
    assert "vector" in rrf[0]["component_scores"]
    assert rrf[0]["fusion_method"] == "rrf"


def test_hybrid_search_preserves_component_scores_in_explain(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    result = client.hybrid_search(
        "foia agency",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=3,
        candidate_centroids=1,
        fusion=FusionConfig(method="weighted", bm25_weight=0.5, vector_weight=0.5),
        hydrate=True,
    )
    assert result.mode == "hybrid"
    assert result.result_count >= 1
    assert result.explain["component_scores_preserved"] is True
    assert result.explain["fusion"]["method"] == "weighted"
    assert result.results[0]["entry_cid"] == "entry-a"
    for hit in result.results:
        assert "bm25_score" in hit
        assert "vector_score" in hit
        assert "component_scores" in hit
        assert set(hit["component_scores"]) == {"bm25", "vector"}
        assert hit["component_scores"]["bm25"] == hit["bm25_score"]
        assert hit["component_scores"]["vector"] == hit["vector_score"]
    # Explain also carries per-hit component scores for audit.
    explain_scores = result.explain["hit_component_scores"]
    assert len(explain_scores) == result.result_count
    assert explain_scores[0]["entry_cid"] == "entry-a"
    assert "bm25_score" in explain_scores[0]
    assert "vector_score" in explain_scores[0]


def test_hybrid_rrf_preserves_component_scores(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = hybrid_search(
        client,
        "agency privacy",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=3,
        fusion=FusionConfig(method="rrf", rrf_k=60),
        hydrate=True,
    )
    assert result.mode == "hybrid"
    assert result.explain["fusion"]["method"] == "rrf"
    for hit in result.results:
        assert "component_scores" in hit
        assert "bm25" in hit["component_scores"]
        assert "vector" in hit["component_scores"]


def test_hybrid_legal_title_filter(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.hybrid_search(
        "agency",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=5,
        filters=LegalFilters(title="5"),
        hydrate=True,
    )
    assert result.result_count >= 1
    for hit in result.results:
        assert str(hit.get("title")) == "5"


def test_hybrid_citation_and_version_filters(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.hybrid_search(
        "agency",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=5,
        filters={"citation": "5 U.S.C. § 552", "version": "2024"},
        hydrate=True,
    )
    assert result.result_count >= 1
    assert result.results[0]["entry_cid"] == "entry-a"
    assert result.results[0].get("citation") == "5 U.S.C. § 552"


# ---------------------------------------------------------------------------
# Graph walk enforces all budgets
# ---------------------------------------------------------------------------


def test_graph_walk_enforces_node_budget(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        limits=QueryLimits(
            max_bytes=10_000_000,
            max_shards=32,
            max_rows=10_000,
            max_nodes=2,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )
    result = client.graph_walk(
        "entry-a",
        direction="out",
        max_depth=3,
        max_nodes=2,
        per_node_limit=10,
    )
    assert result.mode == "graph_walk"
    assert result.complete is False
    assert result.stop_reason == "nodes"
    assert result.diagnostics["node_count"] <= 2
    assert set(result.explain["budgets_enforced"]) == set(BUDGET_DIMENSIONS)
    assert set(result.diagnostics["budgets_enforced"]) == set(BUDGET_DIMENSIONS)
    # Edges still carry sealed authority labels.
    for edge in result.edges:
        if edge.get("edge_type") == "BM25_NEIGHBOR_OF":
            assert edge["legal_authority"] is False
        if edge.get("edge_type") == "CONTAINS":
            assert edge["legal_authority"] is True


def test_graph_walk_module_level_entry_point(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = graph_walk(
        client,
        "entry-a",
        max_depth=1,
        max_nodes=10,
        include_similarity=False,
    )
    assert result.mode == "graph_walk"
    # Similarity edges filtered out.
    for edge in result.edges:
        assert edge.get("edge_type") != "BM25_NEIGHBOR_OF"
        assert edge.get("legal_authority") is True


def test_graph_walk_edge_budget(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        limits=QueryLimits(
            max_bytes=10_000_000,
            max_shards=32,
            max_rows=10_000,
            max_nodes=64,
            max_edges=1,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )
    result = client.graph_walk(
        "entry-a",
        max_depth=3,
        max_edges=1,
        per_node_limit=10,
    )
    assert result.complete is False
    assert result.stop_reason == "edges"
    assert result.diagnostics["edge_count"] <= 1


# ---------------------------------------------------------------------------
# Off-centroid frontier vector selective fetch
# ---------------------------------------------------------------------------


def test_select_vector_shards_for_keys_is_selective() -> None:
    meta = [
        {
            "first_key": "entry-a",
            "last_key": "entry-a",
            "relative_path": "data/vectors/centroid-000000-part-000000.parquet",
            "shard_id": 0,
        },
        {
            "first_key": "entry-b",
            "last_key": "entry-c",
            "relative_path": "data/vectors/centroid-000001-part-000000.parquet",
            "shard_id": 1,
        },
    ]
    selected = select_vector_shards_for_keys(meta, ["entry-b", "entry-c"])
    assert set(selected) == {"entry-b", "entry-c"}
    assert all(
        row["relative_path"].endswith("centroid-000001-part-000000.parquet")
        for row in selected.values()
    )
    # entry-a not requested → its shard is not selected.
    assert "entry-a" not in selected


def test_semantic_beam_fetches_off_centroid_frontier_vectors(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    # Query vector [1,0] routes to centroid 0 (entry-a only).
    # Walk from entry-a expands to entry-b (off-centroid) then entry-c.
    result = client.semantic_graph_walk(
        "entry-a",
        query="foia",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        direction="out",
        beam=SemanticBeamConfig(
            max_depth=2,
            max_nodes=10,
            max_edges=20,
            beam_width=4,
            per_node_limit=10,
            candidate_centroids=1,
        ),
    )
    assert result.mode == "semantic_graph_walk"
    assert result.explain["direct_cid_frontier_fetch"] is True
    assert result.explain["off_centroid_selective_fetch"] is True
    assert result.diagnostics["off_centroid_frontier_vectors_fetched"] is True
    off_paths = set(result.diagnostics["off_centroid_fetch_paths"])
    assert off_paths, "expected at least one off-centroid frontier vector fetch"
    assert any("centroid-000001" in path for path in off_paths)
    # Centroid-0 may also be fetched for the seed; centroid-1 is the off set.
    centroid_paths = set(result.diagnostics["centroid_routed_paths"])
    assert any("centroid-000000" in path for path in centroid_paths)
    for path in off_paths:
        assert path not in centroid_paths

    # Fetch-trace metadata records direct_cid_frontier + off_centroid.
    vector_meta = _trace_vector_meta(result)
    frontier_meta = [
        meta
        for meta in vector_meta
        if meta.get("fetch_policy") == "direct_cid_frontier"
    ]
    assert frontier_meta
    assert any(meta.get("off_centroid") is True for meta in frontier_meta)

    # Results include frontier nodes with semantic scores.
    node_ids = {node["node_cid"] for node in result.results}
    assert "entry-a" in node_ids
    assert "entry-b" in node_ids
    # Similarity edges never legal authority.
    for edge in result.edges:
        if edge.get("edge_type") == "BM25_NEIGHBOR_OF":
            assert edge["legal_authority"] is False


def test_semantic_graph_walk_module_level(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = semantic_graph_walk(
        client,
        "entry-a",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        beam={"max_depth": 1, "beam_width": 4, "candidate_centroids": 1},
    )
    assert result.mode == "semantic_graph_walk"
    assert result.result_count >= 1


def test_fetch_frontier_vectors_is_selective(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.reset_session()
    client.engine._manifest_required()
    client._probe_centroid_paths([1.0, 0.0], candidate_centroids=1)
    vectors = client.fetch_frontier_vectors(
        ["entry-b"],
        query_vector=[1.0, 0.0],
        candidate_centroids=1,
    )
    assert "entry-b" in vectors
    assert client._off_centroid_fetch_paths
    # Only the off-centroid shard for entry-b, not a full centroid dump of
    # unrelated clusters beyond the locator range.
    assert any(
        "centroid-000001" in path
        for path in client._off_centroid_fetch_paths
    )


# ---------------------------------------------------------------------------
# Replay + cosine + misc
# ---------------------------------------------------------------------------


def test_cosine_similarity_basic() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine_similarity([1.0, 0.0], None) == 0.0


def test_query_replay_fingerprint_stable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    a = client.hybrid_search(
        "foia",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=2,
    )
    b = client.hybrid_search(
        "foia",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=2,
    )
    assert query_replay_fingerprint(a) == query_replay_fingerprint(b)
    assert a.ordered_result_cids() == b.ordered_result_cids()


def test_fixture_cases_drive_acceptance(tmp_path: Path) -> None:
    """Execute sealed fixture recipes end-to-end."""

    payload = load_uscode_query_expected_fixture(FIXTURE_PATH)
    cases = {case["id"]: case for case in payload["cases"]}
    client = _client(tmp_path)

    # hybrid weighted
    case = cases["hybrid_weighted_preserves_component_scores"]
    result = client.hybrid_search(
        case["query"],
        query_vector=case["query_vector"],
        model_space=_release_space(),
        top_k=case["top_k"],
        fusion=case["fusion"],
        hydrate=True,
    )
    assert result.results[0]["entry_cid"] == case["expected_top_entry_cid"]
    for hit in result.results:
        assert set(hit["component_scores"]) == set(
            case["expected_component_score_keys"]
        )

    # hybrid rrf
    case = cases["hybrid_rrf_preserves_component_scores"]
    result = client.hybrid_search(
        case["query"],
        query_vector=case["query_vector"],
        model_space=_release_space(),
        top_k=case["top_k"],
        fusion=case["fusion"],
        hydrate=True,
    )
    for hit in result.results:
        assert set(hit["component_scores"]) == set(
            case["expected_component_score_keys"]
        )

    # graph walk budget
    case = cases["graph_walk_enforces_node_budget"]
    tight = _client(
        tmp_path / "graph",
        limits=QueryLimits(
            max_bytes=10_000_000,
            max_shards=32,
            max_rows=10_000,
            max_nodes=case["max_nodes"],
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )
    # Fixture uses node-a; our unified release uses entry-a.
    start = "entry-a"
    result = tight.graph_walk(
        start,
        max_depth=case["max_depth"],
        max_nodes=case["max_nodes"],
    )
    assert result.stop_reason == case["expected_stop_reason"]

    # semantic off-centroid
    case = cases["semantic_beam_off_centroid_frontier_fetch"]
    result = client.semantic_graph_walk(
        "entry-a",
        query=case["query"],
        query_vector=case["query_vector"],
        model_space=_release_space(),
        beam=SemanticBeamConfig(
            max_depth=case["max_depth"],
            candidate_centroids=1,
            beam_width=4,
        ),
    )
    assert (
        result.diagnostics["off_centroid_frontier_vectors_fetched"]
        is case["expected_off_centroid_fetch"]
    )

    # authority
    case = cases["similarity_edge_never_legal_authority"]
    classified = classify_edge_authority(case["edge_type"])
    assert classified["legal_authority"] is case["expected_legal_authority"]
    assert classified["proof_authority"] is case["expected_proof_authority"]
