"""Unit tests for direct remote BM25 and vector search modes (USCIR-026).

Acceptance:

* BM25 uses only term-range routes.
* Vectors use only centroid routes plus exact scoring.
* Mutable / mismatched model space fails closed.
* Trace fixtures prove sparse I/O.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    QueryLimits,
    ROUTE_FAMILIES,
    ROUTE_REASONS,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
    GOAL_ID,
    REMOTE_SEARCH_RESULTS_FIXTURE_SCHEMA,
    REMOTE_SEARCH_SCHEMA_VERSION,
    TASK_ID,
    ModelSpace,
    ModelSpaceMismatchError,
    MutableModelSpaceError,
    RemoteSearchClient,
    SearchFilters,
    SparseIoContractError,
    assert_bm25_sparse_io,
    assert_vector_sparse_io,
    bm25_search,
    build_remote_search_results_fixture_payload,
    default_remote_search_results_fixture_path,
    extract_release_model_space,
    is_immutable_model_revision,
    is_mutable_revision_token,
    load_remote_search_results_fixture,
    normalize_scores,
    remote_replay_fingerprint,
    require_immutable_model_revision,
    sparse_io_summary,
    stable_rank,
    vector_search,
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
FIXTURE_PATH = default_remote_search_results_fixture_path()
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


def build_mini_release(
    root: Path,
    *,
    vector_overrides: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Build a descriptor-complete offline release for remote search tests."""

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
            "document_index": 0,
            "entry_cid": "entry-a",
            "release_point": "2024-01",
            "section": "552",
            "source": "uscode",
            "text": "FOIA agency records",
            "title": "5",
        },
        {
            "chapter": "5",
            "document_index": 1,
            "entry_cid": "entry-b",
            "release_point": "2024-01",
            "section": "552a",
            "source": "uscode",
            "text": "Privacy Act agency disclosure",
            "title": "5",
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

    vector_block: dict[str, Any] = {
        "default_probe_centroids": 1,
        "dimension": 2,
        "layout": "semantic_centroid_groups",
        "max_shards_per_centroid": 1,
        "model_id": MODEL_ID,
        "model_name": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "normalization": "l2",
        "vector_space_id": VECTOR_SPACE_ID,
    }
    if vector_overrides:
        vector_block.update(vector_overrides)

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
            "vector_chunks": vector_index_desc,
        },
        "primary_key": "entry_cid",
        "schema_version": "hf-graphrag-release/v1",
        "vector": vector_block,
    }
    (root / "manifest.json").write_bytes(
        canonical_json_dumps(manifest).encode("utf-8")
    )
    return manifest


def _client(
    tmp_path: Path,
    *,
    limits: QueryLimits | None = None,
    vector_overrides: dict[str, Any] | None = None,
    query_embedder=None,
    score_normalization: str = "minmax",
) -> RemoteSearchClient:
    release = tmp_path / "release"
    release.mkdir(parents=True, exist_ok=True)
    build_mini_release(release, vector_overrides=vector_overrides)
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
    return RemoteSearchClient(
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
        query_embedder=query_embedder,
        score_normalization=score_normalization,
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


def _trace_paths(result) -> set[str]:
    return {
        str(item.get("relative_path") or "")
        for item in (result.fetch_trace.get("files") or [])
    }


def _release_space() -> ModelSpace:
    return ModelSpace(
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        vector_space_id=VECTOR_SPACE_ID,
        dimension=2,
        normalization="l2",
    )


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_remote_search_results_fixture_is_sealed() -> None:
    assert FIXTURE_PATH.is_file()
    payload = load_remote_search_results_fixture(FIXTURE_PATH)
    assert payload["schema_version"] == REMOTE_SEARCH_RESULTS_FIXTURE_SCHEMA
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["acceptance"]["bm25_term_range_only"] is True
    assert payload["acceptance"]["vectors_centroid_plus_exact_score"] is True
    assert payload["acceptance"]["mutable_mismatched_model_space_fails"] is True
    assert payload["acceptance"]["sparse_io_trace_proven"] is True
    generated = build_remote_search_results_fixture_payload()
    assert generated["schema_version"] == payload["schema_version"]
    assert generated["cases"] == payload["cases"]
    assert set(generated["route_families"]) == set(ROUTE_FAMILIES)
    assert set(generated["route_reasons"]) == set(ROUTE_REASONS)
    assert generated["remote_search_schema_version"] == REMOTE_SEARCH_SCHEMA_VERSION


def test_fixture_payload_is_deterministic() -> None:
    first = build_remote_search_results_fixture_payload()
    second = build_remote_search_results_fixture_payload()
    assert first == second
    assert canonical_json_dumps(first) == canonical_json_dumps(second)


# ---------------------------------------------------------------------------
# Model space validation
# ---------------------------------------------------------------------------


def test_mutable_revision_tokens_are_rejected() -> None:
    assert is_mutable_revision_token("latest") is True
    assert is_mutable_revision_token("main") is True
    assert is_mutable_revision_token("HEAD") is True
    assert is_immutable_model_revision(MODEL_REVISION) is True
    with pytest.raises(MutableModelSpaceError):
        require_immutable_model_revision("latest")
    with pytest.raises(MutableModelSpaceError):
        ModelSpace(
            model_id=MODEL_ID,
            model_revision="main",
            vector_space_id="space",
            dimension=2,
        )
    with pytest.raises(MutableModelSpaceError):
        ModelSpace(
            model_id="unknown",
            model_revision=MODEL_REVISION,
            vector_space_id=VECTOR_SPACE_ID,
            dimension=2,
        )


def test_extract_release_model_space_from_manifest(tmp_path: Path) -> None:
    client = _client(tmp_path)
    space = client.release_model_space()
    assert space.model_id == MODEL_ID
    assert space.model_revision == MODEL_REVISION
    assert space.vector_space_id == VECTOR_SPACE_ID
    assert space.dimension == 2
    assert space.normalization == "l2"


def test_mutable_model_space_in_manifest_fails(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        vector_overrides={"model_revision": "latest"},
    )
    with pytest.raises(MutableModelSpaceError):
        client.vector_search(query_vector=[1.0, 0.0])


def test_mismatched_model_space_fails(tmp_path: Path) -> None:
    client = _client(tmp_path)
    wrong = ModelSpace(
        model_id="fixture-other-model",
        model_revision="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        vector_space_id=(
            "other@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:d2:norm=l2"
        ),
        dimension=2,
        normalization="l2",
    )
    with pytest.raises(ModelSpaceMismatchError):
        client.vector_search(
            query_vector=[1.0, 0.0],
            model_space=wrong,
        )


def test_query_vector_dimension_mismatch_fails(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with pytest.raises(ModelSpaceMismatchError):
        client.vector_search(query_vector=[1.0, 0.0, 0.0])


def test_query_embedder_hook_matches_model_space(tmp_path: Path) -> None:
    def embedder(text: str, space: ModelSpace) -> list[float]:
        assert space.vector_space_id == VECTOR_SPACE_ID
        assert "entry" in text or text
        return [1.0, 0.0]

    client = _client(tmp_path, query_embedder=embedder)
    result = client.vector_search(
        "near entry-a",
        model_space=_release_space(),
        top_k=1,
        candidate_centroids=1,
        hydrate=True,
    )
    assert result.mode == "vector"
    assert result.results[0]["entry_cid"] == "entry-a"
    assert result.model_space["vector_space_id"] == VECTOR_SPACE_ID


# ---------------------------------------------------------------------------
# BM25 term-range only + sparse I/O
# ---------------------------------------------------------------------------


def test_bm25_uses_only_term_range_routes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bm25_search("foia agency", top_k=2, hydrate=True)
    assert result.mode == "bm25"
    assert result.complete is True
    assert result.result_count >= 1
    assert result.results[0]["entry_cid"] == "entry-a"
    assert "normalized_score" in result.results[0]

    families = _trace_families(result)
    reasons = _trace_reasons(result)
    assert "bm25_postings" in families
    assert "vectors" not in families
    assert "term_range" in reasons
    # Data-plane BM25 reasons must be term_range only.
    for item in result.fetch_trace["files"]:
        route = item["route"]
        if route["family"] == "bm25_postings":
            assert route["reason"] == "term_range"
    posting_paths = {
        item["relative_path"]
        for item in result.fetch_trace["files"]
        if (item.get("route") or {}).get("family") == "bm25_postings"
    }
    # Only the agency/foia term-range shard — not the privacy shard.
    assert posting_paths == {"data/bm25/postings/part-000000.parquet"}
    assert_bm25_sparse_io(result.fetch_trace)
    summary = sparse_io_summary(result.fetch_trace)
    assert "data/bm25/postings/part-000001.parquet" not in summary["paths"]


def test_bm25_module_level_entry_point(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = bm25_search(client, "foia", top_k=1, hydrate=False)
    assert result.mode == "bm25"
    assert result.diagnostics["public_mode"] == "bm25_search"


# ---------------------------------------------------------------------------
# Vector centroid + exact scoring sparse I/O
# ---------------------------------------------------------------------------


def test_vector_uses_only_centroid_routes_and_exact_scoring(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    result = client.vector_search(
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
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
    reasons = _trace_reasons(result)
    assert "vectors" in families
    assert "bm25_postings" not in families
    assert "exact_vector_score" in reasons
    for item in result.fetch_trace["files"]:
        route = item["route"]
        if route["family"] == "vectors":
            assert route["reason"] == "exact_vector_score"
    vector_paths = {
        item["relative_path"]
        for item in result.fetch_trace["files"]
        if (item.get("route") or {}).get("family") == "vectors"
    }
    assert vector_paths == {
        "data/vectors/centroid-000000-part-000000.parquet"
    }
    assert_vector_sparse_io(result.fetch_trace)
    assert (
        "data/vectors/centroid-000001-part-000000.parquet"
        not in _trace_paths(result)
    )


def test_vector_module_level_entry_point(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = vector_search(
        client,
        query_vector=[1.0, 0.0],
        top_k=1,
        candidate_centroids=1,
        hydrate=False,
    )
    assert result.mode == "vector"
    assert result.diagnostics["public_mode"] == "vector_search"


# ---------------------------------------------------------------------------
# Filters, ranking, explanations, selective hydration
# ---------------------------------------------------------------------------


def test_bm25_filters_and_stable_ranking(tmp_path: Path) -> None:
    client = _client(tmp_path)
    unfiltered = client.bm25_search("agency", top_k=5, hydrate=True)
    cids = [item["entry_cid"] for item in unfiltered.results]
    expected_cids = [
        item["entry_cid"]
        for item in sorted(
            unfiltered.results,
            key=lambda item: (
                -float(item["score"]),
                str(item["entry_cid"]),
                int(item["document_index"]),
            ),
        )
    ]
    assert cids == expected_cids
    # Scores should be descending with stable cid order on ties.
    scores = [float(item["score"]) for item in unfiltered.results]
    assert scores == sorted(scores, reverse=True)

    filtered = client.bm25_search(
        "agency",
        top_k=5,
        hydrate=True,
        filters=SearchFilters(entry_cids=("entry-a",)),
    )
    assert filtered.result_count == 1
    assert filtered.results[0]["entry_cid"] == "entry-a"
    assert filtered.filters["entry_cids"] == ["entry-a"]
    assert filtered.results[0].get("title") == "5"
    assert filtered.results[0].get("section") == "552"
    # Explain + sparse diagnostics present.
    assert filtered.explain.get("route_policy") == "term_range_only"
    assert filtered.sparse_io["file_count"] >= 1


def test_selective_hydration_skips_corpus_when_disabled(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bm25_search("foia", top_k=1, hydrate=False)
    families = _trace_families(result)
    assert "corpus" not in families
    assert "bm25_postings" in families


def test_stable_rank_and_normalize_helpers() -> None:
    hits = [
        {"entry_cid": "b", "document_index": 2, "score": 1.0},
        {"entry_cid": "a", "document_index": 1, "score": 1.0},
        {"entry_cid": "c", "document_index": 0, "score": 2.0},
    ]
    ranked = stable_rank(hits, top_k=3)
    assert [item["entry_cid"] for item in ranked] == ["c", "a", "b"]
    normalized = normalize_scores(ranked, method="minmax")
    assert normalized[0]["normalized_score"] == pytest.approx(1.0)
    assert normalized[-1]["normalized_score"] == pytest.approx(0.0)


def test_field_filters_require_hydration(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bm25_search(
        "agency",
        top_k=5,
        hydrate=False,  # filter still hydrates because section is needed
        filters={"section": "552"},
    )
    assert result.result_count == 1
    assert result.results[0]["entry_cid"] == "entry-a"
    assert "corpus" in _trace_families(result)


# ---------------------------------------------------------------------------
# Offline replay + sparse contract helpers
# ---------------------------------------------------------------------------


def test_offline_replay_is_stable(tmp_path: Path) -> None:
    client_a = _client(tmp_path / "a")
    client_b = _client(tmp_path / "b")
    first = client_a.bm25_search("foia agency", top_k=2, hydrate=True)
    second = client_b.bm25_search("foia agency", top_k=2, hydrate=True)
    assert first.ordered_result_cids() == second.ordered_result_cids()
    assert remote_replay_fingerprint(first) == remote_replay_fingerprint(second)

    client_a.reset_session()
    third = client_a.bm25_search("foia agency", top_k=2, hydrate=True)
    assert third.ordered_result_cids() == first.ordered_result_cids()
    assert remote_replay_fingerprint(third) == remote_replay_fingerprint(first)


def test_sparse_io_contract_helpers_reject_violations() -> None:
    bad_bm25 = {
        "files": [
            {
                "relative_path": "data/vectors/x.parquet",
                "route": {
                    "family": "vectors",
                    "reason": "exact_vector_score",
                    "relative_path": "data/vectors/x.parquet",
                },
            }
        ]
    }
    with pytest.raises(SparseIoContractError):
        assert_bm25_sparse_io(bad_bm25)

    bad_vector = {
        "files": [
            {
                "relative_path": "data/bm25/postings/p.parquet",
                "route": {
                    "family": "bm25_postings",
                    "reason": "term_range",
                    "relative_path": "data/bm25/postings/p.parquet",
                },
            }
        ]
    }
    with pytest.raises(SparseIoContractError):
        assert_vector_sparse_io(bad_vector)


# ---------------------------------------------------------------------------
# Fixture case matrix
# ---------------------------------------------------------------------------


def test_fixture_cases_against_mini_release(tmp_path: Path) -> None:
    payload = load_remote_search_results_fixture(FIXTURE_PATH)
    cases = {case["id"]: case for case in payload["cases"]}

    # bm25_term_range_sparse_io
    case = cases["bm25_term_range_sparse_io"]
    client = _client(tmp_path / "bm25")
    result = client.bm25_search(
        case["query"], top_k=case["top_k"], hydrate=True
    )
    assert set(case["expected_families"]) <= _trace_families(result)
    assert set(case["expected_reasons"]) <= _trace_reasons(result)
    assert result.results[0]["entry_cid"] == case["expected_top_entry_cid"]
    for family in case["forbidden_families"]:
        assert family not in _trace_families(result)
    for path in case["forbidden_paths"]:
        assert path not in _trace_paths(result)
    for path in case["expected_data_plane_paths"]:
        assert path in _trace_paths(result)

    # vector_centroid_exact_sparse_io
    case = cases["vector_centroid_exact_sparse_io"]
    client = _client(tmp_path / "vec")
    result = client.vector_search(
        case["query"],
        query_vector=case["query_vector"],
        model_space=_release_space(),
        top_k=case["top_k"],
        candidate_centroids=case["candidate_centroids"],
        hydrate=True,
    )
    assert set(case["expected_families"]) <= _trace_families(result)
    assert set(case["expected_reasons"]) <= _trace_reasons(result)
    assert result.results[0]["entry_cid"] == case["expected_top_entry_cid"]
    for family in case["forbidden_families"]:
        assert family not in _trace_families(result)
    for path in case["forbidden_paths"]:
        assert path not in _trace_paths(result)

    # mutable_model_space_fails
    case = cases["mutable_model_space_fails"]
    overrides = {}
    for key, value in case["mutate_manifest"].items():
        # Support dotted "vector.model_revision" keys.
        leaf = key.split(".")[-1]
        overrides[leaf] = value
    client = _client(tmp_path / "mutable", vector_overrides=overrides)
    with pytest.raises(MutableModelSpaceError):
        client.vector_search(query_vector=case["query_vector"])

    # mismatched_model_space_fails
    case = cases["mismatched_model_space_fails"]
    client = _client(tmp_path / "mismatch")
    with pytest.raises(ModelSpaceMismatchError):
        client.vector_search(
            query_vector=case["query_vector"],
            model_space=case["query_model_space"],
        )

    # bm25_filter_and_stable_rank
    case = cases["bm25_filter_and_stable_rank"]
    client = _client(tmp_path / "filter")
    unfiltered = client.bm25_search(
        case["query"], top_k=case["top_k"], hydrate=True
    )
    assert [item["entry_cid"] for item in unfiltered.results] == case[
        "expected_order"
    ]
    client.reset_session()
    filtered = client.bm25_search(
        case["query"],
        top_k=case["top_k"],
        hydrate=True,
        filters={"entry_cid": case["filter_entry_cid"]},
    )
    assert filtered.result_count == 1
    assert filtered.results[0]["entry_cid"] == case["filter_entry_cid"]


def test_schema_identity() -> None:
    assert TASK_ID == "USCIR-026"
    assert GOAL_ID == "USCIR-G070"
    assert REMOTE_SEARCH_SCHEMA_VERSION.endswith("/v1")
    assert content_sha256("stable") == content_sha256("stable")
    space = extract_release_model_space(
        {
            "vector": {
                "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "vector_space_id": VECTOR_SPACE_ID,
                "dimension": 2,
                "normalization": "l2",
            }
        }
    )
    assert space.dimension == 2
