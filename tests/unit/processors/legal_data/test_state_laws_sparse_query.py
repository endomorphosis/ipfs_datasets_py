"""Unit tests for bounded immutable-Hub state-law queries (LCR-033).

Acceptance:

* BM25, vector, hybrid, neighbors, bounded graph, and semantic graph modes.
* Jurisdiction / code / citation filters.
* Only justified routed shards are fetched.
* Immutable pins/digests/path/resource checks fail closed (no mutable ``main``).
* Results are stable by CID with auditable traces.
* Similarity / BM25 neighbors are not legal authority.
* Fake-Hub / LocalRootTransport only; consume LCR-032 mini-release identity
  read-only. No live Hub.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_SOURCE_REVISION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    TASK_ID as HF_RELEASE_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_query import (
    ACCEPTANCE_BUDGET_NAMES,
    BM25_ROUTE_POLICY,
    CONSUMED_PRODUCERS,
    CONTRACT_SCHEMA_VERSION,
    ENTRY_LOCATOR_INDEX_NAME,
    FRONTIER_HYDRATION_POLICY,
    FUSION_METHODS,
    FUSION_STAGE,
    GOAL_ID,
    HUB_UPLOAD,
    HYBRID_FUSION_POLICY,
    PROGRAM_ID,
    QUERY_FILTERS,
    QUERY_MODES,
    SCHEMA_VERSION,
    TASK_ID,
    TRAVERSAL_BUDGET_DIMENSIONS,
    VECTOR_ROUTE_POLICY,
    FusionConfig,
    ImmutablePinError,
    LegalAuthorityCollisionError,
    LegalFilters,
    SemanticBeamConfig,
    StateLawsQueryClient,
    StateLawsQueryInputError,
    annotate_edge_authority,
    assert_no_similarity_as_legal_authority,
    build_query_contract_payload,
    classify_edge_authority,
    cosine_similarity,
    default_query_contract_path,
    fuse_hybrid_results,
    graph_walk,
    hybrid_search,
    is_similarity_edge_type,
    load_query_contract,
    parse_entry_locator_locations,
    query_replay_fingerprint,
    rankings_are_compatible,
    require_immutable_revision,
    select_entry_locator_pages_for_keys,
    select_term_range_shards,
    semantic_graph_walk,
    similarity_edge_semantics,
    vector_shard_lexical_range_would_miss,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    BUDGET_DIMENSIONS,
    QueryBudgetExhausted,
    QueryIntegrityError,
    QueryLimits,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import ModelSpace
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    DigestDriftError,
    ImmutableHubResolver,
    LocalRootTransport,
    MutableRevisionError,
    UnsafePathError,
    build_descriptor_for_bytes,
    safe_relative_path,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import canonical_json_dumps

PINNED_REVISION = DEFAULT_SOURCE_REVISION
REPO_ID = DEFAULT_DATASET_REPO_ID
MODEL_REVISION = PINNED_MODEL_REVISION
MODEL_ID = PINNED_MODEL_ID
VECTOR_SPACE_ID = f"gte-small@{MODEL_REVISION}:d2:norm=l2"
CONTRACT_PATH = default_query_contract_path()


# ---------------------------------------------------------------------------
# Miniature offline release
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
    """Build a descriptor-complete offline state-law query release.

    Graph layout (node CIDs == entry CIDs):

    * entry-a --CITES--> entry-b --CONTAINS--> entry-c
    * entry-a --BM25_NEIGHBOR_OF--> entry-b  (similarity)

    Vector shards are cosine-sorted: ``first_key`` / ``last_key`` are
    **not** lexical CID ranges. Frontier hydration must use the dedicated
    entry locator.
    """

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
            "citation": "ORS 192.311",
            "code": "ORS",
            "code_family": "ORS",
            "document_index": 0,
            "entry_cid": "entry-a",
            "jurisdiction": "OR",
            "legal_id": "state:or:ors:192:311",
            "release_point": "or/ors/2024-edition",
            "source": "state-laws",
            "text": "FOIA agency records",
            "title": "192",
        },
        {
            "citation": "ORS 192.355",
            "code": "ORS",
            "code_family": "ORS",
            "document_index": 1,
            "entry_cid": "entry-b",
            "jurisdiction": "OR",
            "legal_id": "state:or:ors:192:355",
            "release_point": "or/ors/2024-edition",
            "source": "state-laws",
            "text": "Privacy Act agency disclosure",
            "title": "192",
        },
        {
            "citation": "D.C. Code § 2-531",
            "code": "DC",
            "code_family": "DC",
            "document_index": 2,
            "entry_cid": "entry-c",
            "jurisdiction": "DC",
            "legal_id": "state:dc:dc:2:531",
            "release_point": "dc/dc/2024-edition",
            "source": "state-laws",
            "text": "Public records inspection",
            "title": "2",
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
            "first_key": "zzz-a",
            "kind": "vectors",
            "last_key": "zzz-a",
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
            "first_key": "aaa-b",
            "kind": "vectors",
            "last_key": "aaa-c",
            "shard_centroid": [-0.9, 0.1],
            "shard_id": 1,
        },
    ]
    vector_index_path = root / "indexes/vector_chunks.parquet"
    _write_parquet(vector_index_path, vector_meta)
    vector_index_desc = _desc(vector_index_path, root, row_count=2)

    locator_page_a = [
        {
            "cluster_id": 0,
            "entry_cid": "entry-a",
            "global_shard_id": 0,
            "relative_path": "data/vectors/centroid-000000-part-000000.parquet",
            "row_offset": 0,
        }
    ]
    locator_page_bc = [
        {
            "cluster_id": 1,
            "entry_cid": "entry-b",
            "global_shard_id": 1,
            "relative_path": "data/vectors/centroid-000001-part-000000.parquet",
            "row_offset": 0,
        },
        {
            "cluster_id": 1,
            "entry_cid": "entry-c",
            "global_shard_id": 1,
            "relative_path": "data/vectors/centroid-000001-part-000000.parquet",
            "row_offset": 1,
        },
    ]
    loc_a_path = root / "indexes/vector_entry_locator/part-000000.parquet"
    loc_bc_path = root / "indexes/vector_entry_locator/part-000001.parquet"
    _write_parquet(loc_a_path, locator_page_a)
    _write_parquet(loc_bc_path, locator_page_bc)
    loc_a_desc = _desc(loc_a_path, root, row_count=1)
    loc_bc_desc = _desc(loc_bc_path, root, row_count=2)
    locator_meta = [
        {
            **loc_a_desc,
            "first_key": "entry-a",
            "kind": "vector_entry_locator",
            "last_key": "entry-a",
            "shard_id": 0,
        },
        {
            **loc_bc_desc,
            "first_key": "entry-b",
            "kind": "vector_entry_locator",
            "last_key": "entry-c",
            "shard_id": 1,
        },
    ]
    locator_index_path = root / "indexes/vector_entry_locator.parquet"
    _write_parquet(locator_index_path, locator_meta)
    locator_index_desc = _desc(locator_index_path, root, row_count=2)

    adj_rows = [
        {
            "edge_cid": "edge-a-b-cites",
            "edge_type": "CITES",
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
            "edge_cid": "edge-b-c-related",
            "edge_type": "CONTAINS",
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
            "tokenizer": "state-laws-bm25-tokenizer/v1",
        },
        "indexes": {
            "bm25_keyword_shards": keyword_desc,
            "corpus_chunks": corpus_index_desc,
            "graph_out_adjacency": adj_index_desc,
            "vector_chunks": vector_index_desc,
            ENTRY_LOCATOR_INDEX_NAME: locator_index_desc,
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
    revision: str = PINNED_REVISION,
) -> StateLawsQueryClient:
    release = tmp_path / "release"
    release.mkdir(parents=True, exist_ok=True)
    build_mini_release(release)
    resolver = ImmutableHubResolver(
        repo_id=REPO_ID,
        revision=revision,
        cache_dir=tmp_path / "cache",
        transport=LocalRootTransport(release),
        local_root=release,
        supported_schemas={
            "hf-graphrag-release/v1",
            "state-laws-ir-graphrag/v2",
            "publicus-ir-graphrag/v2",
        },
    )
    return StateLawsQueryClient(
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


def _trace_routes(result) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for item in result.fetch_trace.get("files") or []:
        route = item.get("route") or {}
        if route:
            routes.append(dict(route))
    return routes


def _vector_meta_rows() -> list[dict[str, Any]]:
    return [
        {
            "first_key": "zzz-a",
            "last_key": "zzz-a",
            "relative_path": "data/vectors/centroid-000000-part-000000.parquet",
            "shard_id": 0,
        },
        {
            "first_key": "aaa-b",
            "last_key": "aaa-c",
            "relative_path": "data/vectors/centroid-000001-part-000000.parquet",
            "shard_id": 1,
        },
    ]


# ---------------------------------------------------------------------------
# Contract integrity
# ---------------------------------------------------------------------------


def test_query_contract_is_sealed() -> None:
    assert CONTRACT_PATH.is_file()
    payload = load_query_contract(CONTRACT_PATH)
    assert payload["schema_version"] == CONTRACT_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["program_id"] == PROGRAM_ID
    assert payload["query_schema_version"] == SCHEMA_VERSION
    acceptance = payload["acceptance"]
    assert acceptance["bm25_routes_by_lexicographic_term_ranges"] is True
    assert acceptance["dense_retrieval_probes_evaluated_centroids"] is True
    assert acceptance["hybrid_scores_late_fuse_compatible_rankings"] is True
    assert (
        acceptance[
            "semantic_graph_traversal_hydrates_frontier_through_entry_locator"
        ]
        is True
    )
    assert (
        acceptance["traversal_budgets_include_depth_node_edge_shard_byte_time"]
        is True
    )
    assert acceptance["hub_upload"] is False
    assert acceptance["secrets_absent"] is True
    assert acceptance["immutable_pin_required"] is True
    assert acceptance["no_mutable_main_default"] is True
    generated = build_query_contract_payload()
    assert generated["schema_version"] == payload["schema_version"]
    assert generated["acceptance"] == payload["acceptance"]
    assert generated["routing"] == payload["routing"]
    assert generated["fusion"] == payload["fusion"]
    assert set(generated["bounds"]["budget_dimensions"]) == set(
        BUDGET_DIMENSIONS
    )
    assert set(generated["bounds"]["fusion_methods"]) == set(FUSION_METHODS)
    assert generated["bounds"]["fusion_stage"] == FUSION_STAGE
    assert generated["routing"]["bm25"] == BM25_ROUTE_POLICY
    assert generated["routing"]["vector"] == VECTOR_ROUTE_POLICY
    assert generated["routing"]["hybrid"] == HYBRID_FUSION_POLICY
    assert generated["routing"]["frontier_hydration"] == FRONTIER_HYDRATION_POLICY
    assert set(generated["traversal_budgets"]) == set(
        TRAVERSAL_BUDGET_DIMENSIONS
    )
    assert set(generated["bounds"]["acceptance_budget_names"]) == set(
        ACCEPTANCE_BUDGET_NAMES
    )
    assert payload["authorizing_for_release"] is False
    assert payload["authorizing_for_publication"] is False
    assert payload["authorizing_hub_upload"] is False
    assert payload["hub_upload"] is False
    assert HUB_UPLOAD is False
    assert payload["secrets_absent"] is True
    assert payload["immutable_pin_required"] is True
    assert payload["no_mutable_main_default"] is True
    assert payload["filters"] == list(QUERY_FILTERS)
    assert set(payload["modes"]) == set(QUERY_MODES)
    assert payload["consumed_modules"]["bm25"] == "state_laws_bm25"
    assert payload["consumed_modules"]["vectors"] == "state_laws_vectors"
    assert payload["consumed_modules"]["graph"] == "state_laws_graph"
    assert payload["consumed_modules"]["adjacency"] == "state_laws_adjacency"
    assert payload["consumed_modules"]["hf_release"] == "state_laws_hf_release"
    assert HF_RELEASE_TASK_ID == "LCR-032"
    assert "state_laws_hf_release" in CONSUMED_PRODUCERS


def test_contract_payload_is_deterministic() -> None:
    first = build_query_contract_payload()
    second = build_query_contract_payload()
    assert first == second
    assert canonical_json_dumps(first) == canonical_json_dumps(second)


def test_contract_matches_on_disk_receipt() -> None:
    payload = load_query_contract(CONTRACT_PATH)
    generated = build_query_contract_payload()
    assert generated == payload


# ---------------------------------------------------------------------------
# Immutable pin fail-closed (compose shared resolver; do not rewrite it)
# ---------------------------------------------------------------------------


def test_mutable_main_revision_fails_closed() -> None:
    with pytest.raises((ImmutablePinError, MutableRevisionError)):
        require_immutable_revision("main")
    with pytest.raises((ImmutablePinError, MutableRevisionError)):
        require_immutable_revision("latest")
    with pytest.raises(MutableRevisionError):
        ImmutableHubResolver(
            repo_id=REPO_ID,
            revision="main",
            cache_dir="/tmp/unused-state-laws-query-cache",
            transport=LocalRootTransport(Path("/tmp")),
            local_root=Path("/tmp"),
        )


def test_client_requires_immutable_resolver(tmp_path: Path) -> None:
    with pytest.raises(StateLawsQueryInputError):
        StateLawsQueryClient(None)
    pinned = require_immutable_revision(PINNED_REVISION)
    assert pinned == PINNED_REVISION
    client = _client(tmp_path)
    assert client.resolver.revision == PINNED_REVISION
    assert client.resolver.repo_id == REPO_ID


def test_fixture_transport_is_local_not_live_hub(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert isinstance(client.resolver.transport, LocalRootTransport)
    result = client.bm25_search("foia", top_k=1, hydrate=False)
    assert result.task_id == TASK_ID
    assert result.goal_id == GOAL_ID
    for item in result.fetch_trace.get("files") or []:
        assert "huggingface.co" not in str(item.get("relative_path") or "")


# ---------------------------------------------------------------------------
# BM25 lexicographic term-range routing
# ---------------------------------------------------------------------------


def test_select_term_range_shards_is_lexicographic() -> None:
    meta = [
        {
            "first_key": "agency",
            "last_key": "foia",
            "relative_path": "data/bm25/postings/part-000000.parquet",
            "shard_id": 0,
        },
        {
            "first_key": "privacy",
            "last_key": "privacy",
            "relative_path": "data/bm25/postings/part-000001.parquet",
            "shard_id": 1,
        },
    ]
    foia = select_term_range_shards(meta, ["foia"])
    assert set(foia) == {"foia"}
    assert foia["foia"]["relative_path"].endswith("part-000000.parquet")
    privacy = select_term_range_shards(meta, ["privacy"])
    assert privacy["privacy"]["relative_path"].endswith("part-000001.parquet")
    assert "part-000000" not in privacy["privacy"]["relative_path"]


def test_bm25_search_routes_by_lexicographic_term_ranges(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bm25_search("privacy", top_k=3, hydrate=True)
    assert result.mode == "bm25"
    assert result.explain["route_policy"] == BM25_ROUTE_POLICY
    paths = _trace_paths(result)
    assert any("part-000001" in path for path in paths)
    assert not any(
        path.endswith("data/bm25/postings/part-000000.parquet") for path in paths
    )
    reasons = {route.get("reason") for route in _trace_routes(result)}
    assert "term_range" in reasons
    families = {route.get("family") for route in _trace_routes(result)}
    assert "bm25_postings" in families
    assert "vectors" not in families


def test_bm25_foia_does_not_fetch_privacy_shard(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bm25_search("foia", top_k=3, hydrate=False)
    paths = _trace_paths(result)
    assert any(
        path.endswith("data/bm25/postings/part-000000.parquet") for path in paths
    )
    assert not any(
        path.endswith("data/bm25/postings/part-000001.parquet") for path in paths
    )
    assert result.result_count >= 1
    assert result.results[0]["entry_cid"] == "entry-a"


# ---------------------------------------------------------------------------
# Dense retrieval probes evaluated centroids
# ---------------------------------------------------------------------------


def test_vector_search_probes_evaluated_centroids(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.vector_search(
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=3,
        candidate_centroids=1,
        hydrate=True,
    )
    assert result.mode == "vector"
    assert result.explain["route_policy"] == VECTOR_ROUTE_POLICY
    routes = _trace_routes(result)
    reasons = {route.get("reason") for route in routes}
    routed = result.diagnostics.get("routed_paths") or result.explain.get(
        "routed_shards"
    )
    assert routed or "centroid_probe" in reasons
    assert result.diagnostics.get("route_policy") == VECTOR_ROUTE_POLICY
    families = {route.get("family") for route in routes}
    assert "vectors" in families
    assert "bm25_postings" not in families
    paths = _trace_paths(result)
    assert any("centroid-000000" in path for path in paths)
    assert not any(
        path.endswith("data/vectors/centroid-000001-part-000000.parquet")
        for path in paths
    )
    assert result.result_count >= 1
    assert result.results[0]["entry_cid"] == "entry-a"


# ---------------------------------------------------------------------------
# Hybrid late-fuses compatible rankings
# ---------------------------------------------------------------------------


def test_rankings_are_compatible_on_shared_identity() -> None:
    left = [{"entry_cid": "entry-a", "score": 1.0}]
    right = [{"entry_cid": "entry-b", "score": 0.5}]
    assert rankings_are_compatible(left, right) is True
    assert rankings_are_compatible(left, []) is True


def test_fuse_hybrid_results_late_preserves_component_scores() -> None:
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
    assert hit["fusion_method"] == "weighted"
    assert hit["fusion_stage"] == "late"

    rrf = fuse_hybrid_results(
        bm25,
        vector,
        config=FusionConfig(method="rrf", rrf_k=60),
        top_k=5,
    )
    assert rrf[0]["component_scores"]["bm25"] >= 0.0
    assert "vector" in rrf[0]["component_scores"]
    assert rrf[0]["fusion_method"] == "rrf"
    assert rrf[0]["fusion_stage"] == "late"


def test_hybrid_search_late_fuses_compatible_rankings(tmp_path: Path) -> None:
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
    assert result.explain["component_scores_preserved"] is True
    assert result.explain["fusion_stage"] == "late"
    assert result.explain["fusion_policy"] == HYBRID_FUSION_POLICY
    assert result.explain["compatible_rankings"] is True
    assert result.explain["bm25_route_policy"] == BM25_ROUTE_POLICY
    assert result.explain["vector_route_policy"] == VECTOR_ROUTE_POLICY
    assert result.results[0]["entry_cid"] == "entry-a"
    for hit in result.results:
        assert "bm25_score" in hit
        assert "vector_score" in hit
        assert "component_scores" in hit
        assert set(hit["component_scores"]) == {"bm25", "vector"}
        assert hit["component_scores"]["bm25"] == hit["bm25_score"]
        assert hit["component_scores"]["vector"] == hit["vector_score"]
        assert hit["fusion_stage"] == "late"
    routes = _trace_routes(result)
    reasons = {route.get("reason") for route in routes}
    assert "term_range" in reasons
    families = {route.get("family") for route in routes}
    assert "bm25_postings" in families
    assert "vectors" in families


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
    assert result.explain["fusion_stage"] == "late"
    for hit in result.results:
        assert "component_scores" in hit
        assert "bm25" in hit["component_scores"]
        assert "vector" in hit["component_scores"]


def test_hybrid_jurisdiction_filter(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.hybrid_search(
        "agency",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=5,
        filters=LegalFilters(jurisdiction="OR"),
        hydrate=True,
    )
    assert result.result_count >= 1
    for hit in result.results:
        assert str(hit.get("jurisdiction")).upper() == "OR"


def test_hybrid_code_and_citation_filters(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.hybrid_search(
        "agency",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        top_k=5,
        filters={"code": "ORS", "citation": "ORS 192.311"},
        hydrate=True,
    )
    assert result.result_count >= 1
    assert result.results[0]["entry_cid"] == "entry-a"
    for hit in result.results:
        assert str(hit.get("code")).upper() == "ORS"
        assert "192.311" in str(hit.get("citation"))


def test_citation_filter_isolates_dc(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bm25_search(
        "agency",
        top_k=5,
        filters=LegalFilters(jurisdiction="DC", code="DC"),
        hydrate=True,
    )
    # "agency" term hits entry-a/b; DC entry-c is not in that posting.
    # Vector/hybrid would still apply filters. Empty is acceptable here.
    for hit in result.results:
        assert str(hit.get("jurisdiction")).upper() == "DC"


# ---------------------------------------------------------------------------
# Authority: similarity never legal authority
# ---------------------------------------------------------------------------


def test_similarity_edge_classification_is_non_authoritative() -> None:
    for edge_type in ("BM25_NEIGHBOR_OF", "SIMILAR_TO", "EMBEDDING_NEIGHBOR_OF"):
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

    amends = classify_edge_authority("AMENDS")
    assert amends["legal_authority"] is True
    assert amends["edge_class"] == "authority"
    contains = classify_edge_authority("CONTAINS")
    assert contains["legal_authority"] is True
    assert contains["edge_class"] == "structural"

    semantics = similarity_edge_semantics()
    assert semantics["legal_authority"] is False
    assert "EMBEDDING_NEIGHBOR_OF" in semantics["edge_types"]
    assert "BM25_NEIGHBOR_OF" in semantics["edge_types"]


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
                "edge_type": "EMBEDDING_NEIGHBOR_OF",
                "authority": "legal",
                "neighbor_cid": "entry-b",
            }
        )
    with pytest.raises(LegalAuthorityCollisionError):
        assert_no_similarity_as_legal_authority(
            [
                {
                    "edge_type": "SIMILAR_TO",
                    "legal_authority": True,
                    "authority": "legal",
                    "proof_authority": True,
                    "edge_class": "authority",
                }
            ]
        )


def test_neighbors_labels_similarity_as_non_authoritative(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.neighbors("entry-a", direction="out", limit=10)
    assert result.mode == "neighbors"
    assert result.edges
    sim_edges = [
        edge
        for edge in result.edges
        if edge.get("edge_type") == "BM25_NEIGHBOR_OF"
    ]
    assert sim_edges
    for edge in sim_edges:
        assert edge["legal_authority"] is False
        assert edge["proof_authority"] is False
        assert edge["authority"] == "non_authoritative"
    legal_edges = [
        edge for edge in result.edges if edge.get("edge_type") == "CITES"
    ]
    assert legal_edges
    assert legal_edges[0]["legal_authority"] is True


# ---------------------------------------------------------------------------
# Graph walk enforces budgets
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
    assert set(result.explain["traversal_budgets"]) == set(
        TRAVERSAL_BUDGET_DIMENSIONS
    )
    for edge in result.edges:
        if edge.get("edge_type") == "BM25_NEIGHBOR_OF":
            assert edge["legal_authority"] is False
        if edge.get("edge_type") == "CITES":
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
    for edge in result.edges:
        assert edge.get("edge_type") != "BM25_NEIGHBOR_OF"
        assert edge.get("legal_authority") is True


def test_bounded_graph_alias(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bounded_graph_walk("entry-a", max_depth=1)
    assert result.mode == "graph_walk"
    assert result.explain["mode_alias"] == "bounded_graph"


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


def test_graph_walk_shard_and_byte_budgets_are_declared(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.graph_walk("entry-a", max_depth=1)
    for dimension in TRAVERSAL_BUDGET_DIMENSIONS:
        assert dimension in result.explain["traversal_budgets"]
    usage = result.usage
    limits = result.limits
    assert "bytes" in usage and "max_bytes" in limits
    assert "shards" in usage and "max_shards" in limits
    assert "rows" in usage and "max_rows" in limits
    assert "time_ms" in usage and "max_time_ms" in limits
    assert "depth" in usage and "max_depth" in limits
    assert "nodes" in usage and "max_nodes" in limits
    assert "edges" in usage and "max_edges" in limits


# ---------------------------------------------------------------------------
# Entry locator frontier hydration
# ---------------------------------------------------------------------------


def test_vector_shard_lexical_ranges_cannot_hydrate_entries() -> None:
    meta = _vector_meta_rows()
    assert vector_shard_lexical_range_would_miss(meta, ["entry-a", "entry-b"])
    selected = select_entry_locator_pages_for_keys(meta, ["entry-a", "entry-b"])
    assert "entry-a" not in selected
    assert "entry-b" not in selected


def test_entry_locator_pages_cover_entry_cids() -> None:
    pages = [
        {
            "first_key": "entry-a",
            "last_key": "entry-a",
            "relative_path": "indexes/vector_entry_locator/part-000000.parquet",
            "shard_id": 0,
        },
        {
            "first_key": "entry-b",
            "last_key": "entry-c",
            "relative_path": "indexes/vector_entry_locator/part-000001.parquet",
            "shard_id": 1,
        },
    ]
    selected = select_entry_locator_pages_for_keys(pages, ["entry-b", "entry-c"])
    assert set(selected) == {"entry-b", "entry-c"}
    assert all(
        row["relative_path"].endswith("part-000001.parquet")
        for row in selected.values()
    )
    assert "entry-a" not in selected


def test_parse_entry_locator_locations_reads_page_rows() -> None:
    rows = [
        {
            "entry_cid": "entry-b",
            "relative_path": "data/vectors/centroid-000001-part-000000.parquet",
            "cluster_id": 1,
            "row_offset": 0,
        }
    ]
    parsed = parse_entry_locator_locations(rows, ["entry-b"])
    assert "entry-b" in parsed
    assert parsed["entry-b"][0]["relative_path"].endswith(
        "centroid-000001-part-000000.parquet"
    )


def test_semantic_beam_hydrates_frontier_through_entry_locator(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
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
    assert result.explain["entry_locator_frontier_fetch"] is True
    assert result.explain["frontier_hydration_policy"] == FRONTIER_HYDRATION_POLICY
    assert result.explain["vector_shard_keys_are_lexical_ranges"] is False
    assert result.explain["off_centroid_selective_fetch"] is True
    assert result.diagnostics["off_centroid_frontier_vectors_fetched"] is True
    assert result.diagnostics["entry_locator_pages_fetched"]
    off_paths = set(result.diagnostics["off_centroid_fetch_paths"])
    assert off_paths
    assert any("centroid-000001" in path for path in off_paths)
    centroid_paths = set(result.diagnostics["centroid_routed_paths"])
    assert any("centroid-000000" in path for path in centroid_paths)
    for path in off_paths:
        assert path not in centroid_paths

    routes = _trace_routes(result)
    locator_meta = [
        route.get("metadata") or {}
        for route in routes
        if (route.get("metadata") or {}).get("fetch_policy") == "entry_locator"
    ]
    assert locator_meta
    frontier_meta = [
        route.get("metadata") or {}
        for route in routes
        if (route.get("metadata") or {}).get("fetch_policy")
        == FRONTIER_HYDRATION_POLICY
    ]
    assert frontier_meta
    assert any(meta.get("off_centroid") is True for meta in frontier_meta)
    assert all(
        meta.get("vector_shard_keys_are_lexical_ranges") is False
        for meta in frontier_meta
    )

    node_ids = {node["node_cid"] for node in result.results}
    assert "entry-a" in node_ids
    assert "entry-b" in node_ids
    for edge in result.edges:
        if edge.get("edge_type") == "BM25_NEIGHBOR_OF":
            assert edge["legal_authority"] is False
    for dimension in TRAVERSAL_BUDGET_DIMENSIONS:
        assert dimension in result.explain["traversal_budgets"]
        assert dimension in result.diagnostics["traversal_budgets"]


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
    assert result.explain["entry_locator_frontier_fetch"] is True


def test_fetch_frontier_vectors_uses_entry_locator_not_shard_keys(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    client.reset_session()
    client.engine._manifest_required()
    client._probe_centroid_paths([1.0, 0.0], candidate_centroids=1)
    assert vector_shard_lexical_range_would_miss(
        client._load_vector_meta(), ["entry-b"]
    )
    vectors = client.fetch_frontier_vectors(
        ["entry-b"],
        query_vector=[1.0, 0.0],
        candidate_centroids=1,
    )
    assert "entry-b" in vectors
    assert client._off_centroid_fetch_paths
    assert any(
        "centroid-000001" in path for path in client._off_centroid_fetch_paths
    )
    assert client._locator_page_paths
    assert any("part-000001" in path for path in client._locator_page_paths)
    assert not any(
        "centroid-000000" in path for path in client._frontier_fetch_paths
    )


def test_semantic_walk_respects_depth_budget(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.semantic_graph_walk(
        "entry-a",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        beam=SemanticBeamConfig(
            max_depth=0,
            beam_width=4,
            candidate_centroids=1,
        ),
    )
    assert result.stop_reason == "depth"
    assert result.diagnostics["node_count"] == 1


def test_semantic_walk_respects_node_budget(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        limits=QueryLimits(
            max_bytes=10_000_000,
            max_shards=32,
            max_rows=10_000,
            max_nodes=1,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )
    result = client.semantic_graph_walk(
        "entry-a",
        query_vector=[1.0, 0.0],
        model_space=_release_space(),
        beam=SemanticBeamConfig(
            max_depth=2,
            max_nodes=1,
            beam_width=4,
            candidate_centroids=1,
        ),
    )
    assert result.complete is False
    assert result.stop_reason in {"nodes", "depth"}
    assert result.diagnostics["node_count"] <= 1


# ---------------------------------------------------------------------------
# Replay + cosine (CID-stable traces)
# ---------------------------------------------------------------------------


def test_cosine_similarity_basic() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine_similarity([1.0, 0.0], None) == 0.0


def test_query_replay_fingerprint_stable_by_cid(tmp_path: Path) -> None:
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
    assert a.ordered_result_cids()
    for item in a.fetch_trace.get("files") or []:
        route = item.get("route") or {}
        assert route.get("family")
        assert route.get("reason")

# ---------------------------------------------------------------------------
# Immutable digest / path / resource fail-closed + revision cache
# ---------------------------------------------------------------------------


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    target = tmp_path / "release" / "data/bm25/postings/part-000000.parquet"
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises((DigestDriftError, QueryIntegrityError)) as caught:
        client.bm25_search("foia", top_k=1, hydrate=False)
    err = caught.value
    if isinstance(err, QueryIntegrityError):
        assert isinstance(err.__cause__, DigestDriftError)


def test_path_traversal_fails_closed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with pytest.raises(UnsafePathError):
        safe_relative_path("../secret.bin")
    with pytest.raises(UnsafePathError):
        safe_relative_path("/etc/passwd")
    with pytest.raises(UnsafePathError):
        client.resolver.resolve("../secret.bin")
    with pytest.raises(UnsafePathError):
        client.resolver.resolve("/etc/passwd")


def test_typed_budget_exhaustion(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        limits=QueryLimits(
            max_bytes=200,
            max_shards=32,
            max_rows=10_000,
            max_nodes=64,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )
    try:
        result = client.bm25_search("foia agency privacy", top_k=3, hydrate=True)
    except QueryBudgetExhausted as exc:
        assert exc.dimension in BUDGET_DIMENSIONS
        payload = exc.to_dict()
        assert payload["dimension"] == exc.dimension
        assert "usage" in payload
        assert "limits" in payload
        return
    assert result.complete is False
    assert result.stop_reason in BUDGET_DIMENSIONS or result.stop_reason in {
        "bytes",
        "shards",
        "rows",
    }


def test_revision_cache_replay_is_stable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = client.bm25_search("foia", top_k=2, hydrate=True)
    second = client.bm25_search("foia", top_k=2, hydrate=True)
    assert query_replay_fingerprint(first) == query_replay_fingerprint(second)
    cache_root = tmp_path / "cache"
    cached = [p for p in cache_root.rglob("*") if p.is_file()]
    assert cached
    assert any(PINNED_REVISION in path.as_posix() for path in cached)
    for path in cached:
        assert "huggingface.co" not in path.as_posix()


def test_query_does_not_full_clone_release(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client.bm25_search("privacy", top_k=1, hydrate=False)
    paths = _trace_paths(result)
    assert "data/bm25/postings/part-000000.parquet" not in paths
    assert not any(path.endswith("data/vectors/centroid-000000-part-000000.parquet") for path in paths)
    assert not any(path.endswith("data/vectors/centroid-000001-part-000000.parquet") for path in paths)
    for item in result.fetch_trace.get("files") or []:
        route = item.get("route") or {}
        assert route.get("reason")
        assert route.get("family")

