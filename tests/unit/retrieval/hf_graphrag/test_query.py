"""Unit tests for the bounded remote query engine (USCIR-025).

Acceptance:

* Every file fetch is route-justified and descriptor-verified.
* Limits cover bytes / shards / rows / nodes / edges / depth / time.
* Offline replay is stable (identical ordered result CIDs + route set).
* Budget exhaustion is explicit (typed partial result, never silent).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    BUDGET_DIMENSIONS,
    GOAL_ID,
    QUERY_ENGINE_SCHEMA_VERSION,
    QUERY_FETCH_TRACES_FIXTURE_SCHEMA,
    ROUTE_FAMILIES,
    ROUTE_REASONS,
    TASK_ID,
    BoundedRemoteQueryEngine,
    DescriptorRequiredError,
    QueryBudgetExhausted,
    QueryLimits,
    RouteJustification,
    UnjustifiedFetchError,
    build_query_fetch_traces_fixture_payload,
    default_query_fetch_traces_fixture_path,
    load_query_fetch_traces_fixture,
    replay_fingerprint,
    select_term_range_shards,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
    build_descriptor_for_bytes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_dumps,
    content_sha256,
)

PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
REPO_ID = "justicedao/ipfs_uscode"
FIXTURE_PATH = default_query_fetch_traces_fixture_path()


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
    """Build a tiny descriptor-complete offline release for query tests."""

    # --- BM25 postings (two term-range shards) ---
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

    # --- Corpus (one shard covering docs 0-1) ---
    corpus_rows = [
        {
            "document_index": 0,
            "entry_cid": "entry-a",
            "text": "FOIA agency records",
            "title": "Freedom of Information Act",
        },
        {
            "document_index": 1,
            "entry_cid": "entry-b",
            "text": "Privacy Act agency disclosure",
            "title": "Privacy Act",
        },
    ]
    corpus_path = root / "data/corpus/part-000000.parquet"
    _write_parquet(corpus_path, corpus_rows)
    corpus_desc = _desc(corpus_path, root, row_count=2)
    corpus_meta = [
        {
            **corpus_desc,
            "end_document_index": 1,
            "first_key": "entry-a",
            "kind": "corpus",
            "last_key": "entry-b",
            "shard_id": 0,
            "start_document_index": 0,
        }
    ]
    corpus_index_path = root / "indexes/corpus_chunks.parquet"
    _write_parquet(corpus_index_path, corpus_meta)
    corpus_index_desc = _desc(corpus_index_path, root, row_count=1)

    # --- Vectors (two centroids, one shard each) ---
    # Cluster 0 near (1, 0); cluster 1 near (-1, 0).
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
        }
    ]
    vec_a_path = root / "data/vectors/centroid-000000-part-000000.parquet"
    vec_b_path = root / "data/vectors/centroid-000001-part-000000.parquet"
    _write_parquet(vec_a_path, vec_a)
    _write_parquet(vec_b_path, vec_b)
    vec_a_desc = _desc(vec_a_path, root, row_count=1)
    vec_b_desc = _desc(vec_b_path, root, row_count=1)
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
            "centroid_min_score": 1.0,
            "centroid_shard_count": 1,
            "chunk_in_cluster": 0,
            "cluster_id": 1,
            "dimension": 2,
            "first_key": "entry-b",
            "kind": "vectors",
            "last_key": "entry-b",
            "shard_centroid": [-1.0, 0.0],
            "shard_id": 1,
        },
    ]
    vector_index_path = root / "indexes/vector_chunks.parquet"
    _write_parquet(vector_index_path, vector_meta)
    vector_index_desc = _desc(vector_index_path, root, row_count=2)

    # --- Graph adjacency (node-a -> node-b, node-b -> node-c) ---
    adj_rows = [
        {
            "edge_cid": "edge-a-b",
            "edge_type": "CONTAINS",
            "neighbor_cid": "node-b",
            "node_cid": "node-a",
            "score": 0.9,
        },
        {
            "edge_cid": "edge-b-c",
            "edge_type": "CITES",
            "neighbor_cid": "node-c",
            "node_cid": "node-b",
            "score": 0.5,
        },
    ]
    adj_path = root / "data/graph/adjacency/out/part-000000.parquet"
    _write_parquet(adj_path, adj_rows)
    adj_desc = _desc(adj_path, root, row_count=2)
    adj_meta = [
        {
            **adj_desc,
            "first_key": "node-a",
            "kind": "graph_adjacency_out",
            "last_key": "node-c",
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
            "model_name": "fixture-unit-v1",
        },
    }
    manifest_bytes = canonical_json_dumps(manifest).encode("utf-8")
    (root / "manifest.json").write_bytes(manifest_bytes)
    return manifest


def _engine(
    tmp_path: Path,
    *,
    limits: QueryLimits | None = None,
) -> BoundedRemoteQueryEngine:
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
    return BoundedRemoteQueryEngine(
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


def _trace_families(result) -> set[str]:
    return {
        str((item.get("route") or {}).get("family") or "")
        for item in (result.fetch_trace.get("files") or [])
    }


def _trace_reasons(result) -> set[str]:
    return {
        str((item.get("route") or {}).get("reason") or "")
        for item in (result.fetch_trace.get("files") or [])
    }


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_query_fetch_traces_fixture_is_sealed() -> None:
    assert FIXTURE_PATH.is_file()
    payload = load_query_fetch_traces_fixture(FIXTURE_PATH)
    assert payload["schema_version"] == QUERY_FETCH_TRACES_FIXTURE_SCHEMA
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert set(payload["budget_dimensions"]) == set(BUDGET_DIMENSIONS)
    assert set(payload["acceptance"]["limits_cover"]) == set(BUDGET_DIMENSIONS)
    assert payload["acceptance"]["route_justified"] is True
    assert payload["acceptance"]["descriptor_verified"] is True
    assert payload["acceptance"]["offline_replay_stable"] is True
    assert payload["acceptance"]["budget_exhaustion_explicit"] is True
    generated = build_query_fetch_traces_fixture_payload()
    assert generated["schema_version"] == payload["schema_version"]
    assert generated["cases"] == payload["cases"]
    assert generated["budget_dimensions"] == payload["budget_dimensions"]
    assert set(generated["route_families"]) == set(ROUTE_FAMILIES)
    assert set(generated["route_reasons"]) == set(ROUTE_REASONS)


def test_fixture_payload_is_deterministic() -> None:
    first = build_query_fetch_traces_fixture_payload()
    second = build_query_fetch_traces_fixture_payload()
    assert first == second
    assert canonical_json_dumps(first) == canonical_json_dumps(second)


# ---------------------------------------------------------------------------
# Route justification + descriptor verification
# ---------------------------------------------------------------------------


def test_fetch_requires_route_justification(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with pytest.raises(UnjustifiedFetchError):
        RouteJustification(
            family="not_a_family",
            reason="term_range",
            relative_path="data/bm25/postings/part-000000.parquet",
        )


def test_data_plane_fetch_requires_descriptor(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.load_manifest()
    route = RouteJustification(
        family="bm25_postings",
        reason="term_range",
        relative_path="data/bm25/postings/part-000000.parquet",
        keys=("foia",),
    )
    with pytest.raises(DescriptorRequiredError):
        engine.fetch(
            "data/bm25/postings/part-000000.parquet",
            route=route,
            descriptor=None,
        )


def test_every_fetch_is_route_justified_and_verified(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    result = engine.run_bm25("foia agency", top_k=2, hydrate=True)
    files = result.fetch_trace["files"]
    assert files
    assert result.fetch_trace["route_justified"] is True
    assert result.fetch_trace["verification_state"] == "verified"
    for item in files:
        assert item["verified"] is True
        route = item["route"]
        assert route["family"] in ROUTE_FAMILIES
        assert route["reason"] in ROUTE_REASONS
        assert route["relative_path"] == item["relative_path"]
        assert item["sha256"]
        # No absolute local paths or credential-like fields.
        rendered = json.dumps(item)
        assert "/home/" not in rendered
        assert "token" not in rendered.lower() or "tokenizer" in rendered.lower()


def test_select_term_range_shards_is_exclusive() -> None:
    meta = [
        {"first_key": "a", "last_key": "m", "relative_path": "p0"},
        {"first_key": "n", "last_key": "z", "relative_path": "p1"},
    ]
    # "0missing" is lexicographically before the first range; omitted (no cover).
    selected = select_term_range_shards(
        meta, ["foia", "privacy", "0missing"]
    )
    assert selected["foia"]["relative_path"] == "p0"
    assert selected["privacy"]["relative_path"] == "p1"
    assert "0missing" not in selected


# ---------------------------------------------------------------------------
# BM25 / vector orchestration
# ---------------------------------------------------------------------------


def test_bm25_routes_terms_and_hydrates(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    result = engine.run_bm25("foia agency", top_k=2, hydrate=True)
    assert result.mode == "bm25"
    assert result.complete is True
    assert result.stop_reason is None
    assert result.result_count >= 1
    assert result.results[0]["entry_cid"] == "entry-a"
    assert "foia" in result.results[0]["matched_terms"]
    families = _trace_families(result)
    reasons = _trace_reasons(result)
    assert "control_plane" in families
    assert "routing_index" in families
    assert "bm25_postings" in families
    assert "corpus" in families
    assert "manifest" in reasons
    assert "term_range" in reasons
    assert "hydrate_hit" in reasons
    # Only the term-range posting shard for agency/foia (part-000000), not privacy.
    posting_paths = {
        item["relative_path"]
        for item in result.fetch_trace["files"]
        if (item.get("route") or {}).get("family") == "bm25_postings"
    }
    assert posting_paths == {"data/bm25/postings/part-000000.parquet"}


def test_vector_centroid_routes_and_exact_scores(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    # Query near cluster 0 (+x).
    result = engine.run_vector(
        [1.0, 0.0],
        query="near entry-a",
        top_k=1,
        candidate_centroids=1,
        hydrate=True,
    )
    assert result.mode == "vector"
    assert result.complete is True
    assert result.result_count == 1
    assert result.results[0]["entry_cid"] == "entry-a"
    assert result.results[0]["score"] == pytest.approx(1.0, abs=1e-5)
    families = _trace_families(result)
    assert "vectors" in families
    assert "corpus" in families
    vector_paths = {
        item["relative_path"]
        for item in result.fetch_trace["files"]
        if (item.get("route") or {}).get("family") == "vectors"
    }
    # Only the selected centroid shard is fetched.
    assert vector_paths == {
        "data/vectors/centroid-000000-part-000000.parquet"
    }


# ---------------------------------------------------------------------------
# Graph walk + budget exhaustion
# ---------------------------------------------------------------------------


def test_graph_walk_budget_nodes_is_explicit(tmp_path: Path) -> None:
    engine = _engine(
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
    result = engine.graph_walk(
        "node-a",
        direction="out",
        max_depth=3,
        max_nodes=2,
        per_node_limit=10,
    )
    assert result.mode == "graph_walk"
    assert result.complete is False
    assert result.stop_reason == "nodes"
    assert result.diagnostics["stop_reason"] == "nodes"
    assert result.diagnostics["node_count"] == 2
    # Partial nodes are still returned.
    assert result.result_count == 2
    cids = {item["node_cid"] for item in result.results}
    assert "node-a" in cids


def test_bm25_shard_budget_exhaustion_is_explicit(tmp_path: Path) -> None:
    # max_shards=2: manifest + keyword index consume both before postings.
    engine = _engine(
        tmp_path,
        limits=QueryLimits(
            max_bytes=10_000_000,
            max_shards=2,
            max_rows=10_000,
            max_nodes=64,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )
    result = engine.run_bm25("foia agency privacy", top_k=3, hydrate=False)
    assert result.complete is False
    assert result.stop_reason == "shards"
    assert result.diagnostics.get("budget_exhausted", {}).get("dimension") == (
        "shards"
    )
    assert result.fetch_trace["stop_reason"] == "shards"
    # Never silently claim completeness under budget pressure.
    assert result.complete is False


def test_query_budget_exhausted_is_typed() -> None:
    usage = {"bytes": 100, "shards": 1, "rows": 0, "nodes": 0, "edges": 0, "depth": 0, "time_ms": 1.0}
    limits = QueryLimits(max_bytes=50).to_dict()
    exc = QueryBudgetExhausted(
        "bytes",
        usage=usage,
        limits=limits,
        partial={"results": [{"entry_cid": "x"}]},
    )
    payload = exc.to_dict()
    assert payload["dimension"] == "bytes"
    assert payload["partial"]["results"][0]["entry_cid"] == "x"
    assert "bytes" in str(exc)


def test_limits_cover_all_acceptance_dimensions() -> None:
    limits = QueryLimits()
    payload = limits.to_dict()
    assert set(BUDGET_DIMENSIONS) == {
        "bytes",
        "shards",
        "rows",
        "nodes",
        "edges",
        "depth",
        "time",
    }
    assert "max_bytes" in payload
    assert "max_shards" in payload
    assert "max_rows" in payload
    assert "max_nodes" in payload
    assert "max_edges" in payload
    assert "max_depth" in payload
    assert "max_time_ms" in payload


# ---------------------------------------------------------------------------
# Offline replay stability
# ---------------------------------------------------------------------------


def test_offline_replay_is_stable(tmp_path: Path) -> None:
    engine_a = _engine(tmp_path / "a")
    first = engine_a.run_bm25("foia agency", top_k=2, hydrate=True)
    # Second session against a fully warmable independent cache root.
    engine_b = _engine(tmp_path / "b")
    second = engine_b.run_bm25("foia agency", top_k=2, hydrate=True)

    assert first.ordered_result_cids() == second.ordered_result_cids()
    assert first.complete == second.complete
    assert first.stop_reason == second.stop_reason
    assert replay_fingerprint(first) == replay_fingerprint(second)

    # Warm-cache replay within the same engine also matches.
    engine_a.reset_session()
    third = engine_a.run_bm25("foia agency", top_k=2, hydrate=True)
    assert third.ordered_result_cids() == first.ordered_result_cids()
    assert replay_fingerprint(third) == replay_fingerprint(first)
    # Cache hits may differ; fingerprint ignores timings/cache flags.
    assert any(
        item.get("cache_hit") for item in third.fetch_trace["files"]
    )


def test_vector_offline_replay_is_stable(tmp_path: Path) -> None:
    engine_a = _engine(tmp_path / "va")
    engine_b = _engine(tmp_path / "vb")
    query = [math.cos(0.1), math.sin(0.1)]
    first = engine_a.run_vector(
        query, top_k=2, candidate_centroids=2, hydrate=True
    )
    second = engine_b.run_vector(
        query, top_k=2, candidate_centroids=2, hydrate=True
    )
    assert first.ordered_result_cids() == second.ordered_result_cids()
    assert replay_fingerprint(first) == replay_fingerprint(second)


# ---------------------------------------------------------------------------
# Fixture case matrix
# ---------------------------------------------------------------------------


def test_fixture_cases_against_mini_release(tmp_path: Path) -> None:
    payload = load_query_fetch_traces_fixture(FIXTURE_PATH)
    cases = {case["id"]: case for case in payload["cases"]}

    # bm25_term_route
    engine = _engine(tmp_path / "bm25")
    case = cases["bm25_term_route"]
    result = engine.run_bm25(case["query"], top_k=case["top_k"], hydrate=True)
    assert case["expected_families"] <= sorted(_trace_families(result)) or (
        set(case["expected_families"]) <= _trace_families(result)
    )
    assert set(case["expected_reasons"]) <= _trace_reasons(result)

    # vector_centroid_route
    engine = _engine(tmp_path / "vec")
    case = cases["vector_centroid_route"]
    result = engine.run_vector(
        [1.0, 0.0],
        top_k=case["top_k"],
        candidate_centroids=case["candidate_centroids"],
        hydrate=True,
    )
    assert set(case["expected_families"]) <= _trace_families(result)
    assert set(case["expected_reasons"]) <= _trace_reasons(result)

    # graph_walk_budget_nodes
    case = cases["graph_walk_budget_nodes"]
    engine = _engine(
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
    result = engine.graph_walk(
        case["start_node_cid"],
        direction=case["direction"],
        max_depth=case["max_depth"],
        max_nodes=case["max_nodes"],
    )
    assert result.stop_reason == case["expected_stop_reason"]
    assert result.complete is False

    # bm25_budget_shards
    case = cases["bm25_budget_shards"]
    engine = _engine(
        tmp_path / "budget",
        limits=QueryLimits(
            max_bytes=10_000_000,
            max_shards=case["max_shards"],
            max_rows=10_000,
            max_nodes=64,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )
    result = engine.run_bm25(case["query"], top_k=3, hydrate=False)
    assert result.stop_reason == case["expected_stop_reason"]
    assert result.complete is False


def test_engine_schema_identity() -> None:
    assert TASK_ID == "USCIR-025"
    assert GOAL_ID == "USCIR-G070"
    assert QUERY_ENGINE_SCHEMA_VERSION.endswith("/v1")
    assert content_sha256("stable") == content_sha256("stable")
