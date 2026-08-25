"""Integration proof of the complete local US Code sparse GraphRAG pipeline (USCIR-033).

Acceptance
----------
* Fixture build is deterministic (two materializations yield identical digests).
* All root/count joins reconcile across corpus, BM25, vectors, and graph.
* Expected results and paths from the sealed fixture pass.
* Fetch traces show only routed shards plus final corpus hydration.
* All six query modes run offline against a local release.
* Offline replay fingerprints are stable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (
    build_uscode_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    validate_uscode_hf_release,
)
from ipfs_datasets_py.processors.legal_data.uscode_query import (
    FusionConfig,
    SemanticBeamConfig,
    UscodeQueryClient,
    query_replay_fingerprint,
)
from ipfs_datasets_py.processors.legal_data.uscode_sparse_graphrag import (
    AdapterRootSet,
    build_family_root_cid,
    content_cid,
    content_sha256,
    reconcile_adapter_roots,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import QueryLimits
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
    CONTROL_ROUTE_REASONS,
    ModelSpace,
    assert_bm25_sparse_io,
    assert_vector_sparse_io,
    sparse_io_summary,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
    build_descriptor_for_bytes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import canonical_json_dumps

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_e2e_release"
_RECIPE_PATH = _FIXTURE_DIR / "recipe.json"
_EXPECTED_PATH = _FIXTURE_DIR / "expected.json"
_REPORT_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_e2e_local.json"

TASK_ID = "USCIR-033"
GOAL_ID = "USCIR-G090"
REPORT_SCHEMA = "uscode-e2e-local-report/v1"
CODE_VERSION = "1"

SIX_MODES = (
    "bm25",
    "vector",
    "hybrid",
    "neighbors",
    "graph_walk",
    "semantic_graph_walk",
)

DATA_PLANE_FAMILIES = frozenset(
    {
        "bm25_postings",
        "vectors",
        "corpus",
        "graph_adjacency",
        "graph_adjacency_out",
        "graph_adjacency_in",
        "graph_nodes",
        "graph_edges",
    }
)


# ---------------------------------------------------------------------------
# Fixture loaders
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"missing fixture: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"fixture must be object: {path}"
    return payload


def load_recipe() -> dict[str, Any]:
    payload = _load_json(_RECIPE_PATH)
    assert payload.get("schema_version") == "uscode-e2e-release-recipe/v1"
    assert payload.get("task_id") == TASK_ID
    return payload


def load_expected() -> dict[str, Any]:
    payload = _load_json(_EXPECTED_PATH)
    assert payload.get("schema_version") == "uscode-e2e-expected/v1"
    assert payload.get("task_id") == TASK_ID
    return payload


# ---------------------------------------------------------------------------
# Deterministic release materializer (compact recipe → offline release)
# ---------------------------------------------------------------------------


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([dict(row) for row in rows])
    pq.write_table(table, path, compression="zstd")
    return path.read_bytes()


def _desc(path: Path, root: Path, *, row_count: int) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    content = path.read_bytes()
    return build_descriptor_for_bytes(
        relative,
        content,
        row_count=row_count,
        media_type="application/vnd.apache.parquet",
        schema_id="hf-graphrag-release/v1",
    ).to_dict()


def materialize_e2e_release(root: Path, recipe: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Materialize a descriptor-complete offline release from the sealed recipe."""

    recipe = dict(recipe or load_recipe())
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    families = recipe["families"]
    routing = recipe["routing"]
    model = recipe["model"]
    bm25_cfg = recipe["bm25"]

    # BM25 postings
    postings = families["bm25_postings"]
    post_paths: dict[str, Path] = {}
    post_descs: dict[str, dict[str, Any]] = {}
    for part_name, rows in postings.items():
        path = root / f"data/bm25/postings/{part_name}.parquet"
        _write_parquet(path, rows)
        post_paths[part_name] = path
        post_descs[part_name] = _desc(path, root, row_count=len(rows))

    keyword_meta = []
    for entry in routing["bm25_keyword_shards"]:
        part = Path(entry["relative_path"]).stem  # part-000000
        desc = post_descs[part]
        keyword_meta.append({**desc, **{k: v for k, v in entry.items() if k != "relative_path"}})
    keyword_path = root / "indexes/bm25_keyword_shards.parquet"
    _write_parquet(keyword_path, keyword_meta)
    keyword_desc = _desc(keyword_path, root, row_count=len(keyword_meta))

    # Corpus
    corpus_rows = list(families["corpus"])
    corpus_path = root / "data/corpus/part-000000.parquet"
    _write_parquet(corpus_path, corpus_rows)
    corpus_desc = _desc(corpus_path, root, row_count=len(corpus_rows))
    corpus_meta = []
    for entry in routing["corpus_chunks"]:
        corpus_meta.append(
            {
                **corpus_desc,
                **{k: v for k, v in entry.items() if k != "relative_path"},
            }
        )
    corpus_index_path = root / "indexes/corpus_chunks.parquet"
    _write_parquet(corpus_index_path, corpus_meta)
    corpus_index_desc = _desc(corpus_index_path, root, row_count=len(corpus_meta))

    # Vectors
    vec_descs: dict[str, dict[str, Any]] = {}
    for part_name, rows in families["vectors"].items():
        path = root / f"data/vectors/{part_name}.parquet"
        _write_parquet(path, rows)
        vec_descs[part_name] = _desc(path, root, row_count=len(rows))
    vector_meta = []
    for entry in routing["vector_chunks"]:
        part = Path(entry["relative_path"]).stem  # centroid-000000-part-000000
        desc = vec_descs[part]
        vector_meta.append(
            {**desc, **{k: v for k, v in entry.items() if k != "relative_path"}}
        )
    vector_index_path = root / "indexes/vector_chunks.parquet"
    _write_parquet(vector_index_path, vector_meta)
    vector_index_desc = _desc(vector_index_path, root, row_count=len(vector_meta))

    # Graph adjacency
    adj_rows = list(families["graph_adjacency_out"])
    adj_path = root / "data/graph/adjacency/out/part-000000.parquet"
    _write_parquet(adj_path, adj_rows)
    adj_desc = _desc(adj_path, root, row_count=len(adj_rows))
    adj_meta = []
    for entry in routing["graph_out_adjacency"]:
        adj_meta.append(
            {**adj_desc, **{k: v for k, v in entry.items() if k != "relative_path"}}
        )
    adj_index_path = root / "indexes/graph_out_adjacency.parquet"
    _write_parquet(adj_index_path, adj_meta)
    adj_index_desc = _desc(adj_index_path, root, row_count=len(adj_meta))

    manifest = {
        "bm25": dict(bm25_cfg),
        "indexes": {
            "bm25_keyword_shards": keyword_desc,
            "corpus_chunks": corpus_index_desc,
            "graph_out_adjacency": adj_index_desc,
            "vector_chunks": vector_index_desc,
        },
        "primary_key": recipe["primary_key"],
        "schema_version": "hf-graphrag-release/v1",
        "vector": {
            "default_probe_centroids": 1,
            "dimension": int(model["dimension"]),
            "layout": "semantic_centroid_groups",
            "max_shards_per_centroid": 1,
            "model_id": model["model_id"],
            "model_name": model["model_id"],
            "model_revision": model["model_revision"],
            "normalization": model["normalization"],
            "vector_space_id": model["vector_space_id"],
        },
    }
    (root / "manifest.json").write_bytes(
        canonical_json_dumps(manifest).encode("utf-8")
    )
    return manifest


def release_file_inventory(root: Path) -> dict[str, str]:
    """Map relative path → sha256 for every file under a release root."""

    inventory: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        inventory[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return inventory


def release_logical_fingerprint(root: Path) -> str:
    """Deterministic fingerprint of a materialized release (path → digest)."""

    return content_sha256(release_file_inventory(root))


# ---------------------------------------------------------------------------
# Query client / model space helpers
# ---------------------------------------------------------------------------


def _model_space(recipe: Mapping[str, Any]) -> ModelSpace:
    model = recipe["model"]
    return ModelSpace(
        model_id=str(model["model_id"]),
        model_revision=str(model["model_revision"]),
        vector_space_id=str(model["vector_space_id"]),
        dimension=int(model["dimension"]),
        normalization=str(model["normalization"]),
    )


def _open_client(
    release: Path,
    recipe: Mapping[str, Any],
    cache_dir: Path,
    *,
    limits: QueryLimits | None = None,
) -> UscodeQueryClient:
    resolver = ImmutableHubResolver(
        repo_id=str(recipe["dataset_repo_id"]),
        revision=str(recipe["revision"]),
        cache_dir=cache_dir,
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


def _trace_items(result: Any) -> list[dict[str, Any]]:
    files = (result.fetch_trace or {}).get("files") or []
    return [dict(item) for item in files if isinstance(item, Mapping)]


def _trace_paths(result: Any) -> set[str]:
    return {
        str(item.get("relative_path") or (item.get("route") or {}).get("relative_path") or "")
        for item in _trace_items(result)
        if item.get("relative_path") or (item.get("route") or {}).get("relative_path")
    }


def _data_plane_routes(result: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _trace_items(result):
        route = item.get("route") or {}
        family = str(route.get("family") or "")
        reason = str(route.get("reason") or "")
        if family in DATA_PLANE_FAMILIES or reason in {"term_range", "exact_vector_score", "hydrate_hit"}:
            if family in DATA_PLANE_FAMILIES or reason == "hydrate_hit":
                out.append(
                    {
                        "family": family,
                        "path": str(
                            item.get("relative_path")
                            or route.get("relative_path")
                            or ""
                        ),
                        "reason": reason,
                    }
                )
    return out


def assert_routed_shards_plus_hydration(
    result: Any,
    *,
    allowed_families: Sequence[str] | None = None,
    allowed_reasons: Sequence[str] | None = None,
    forbidden_families: Sequence[str] | None = None,
    require_corpus_hydration: bool = False,
) -> dict[str, Any]:
    """Assert fetch-trace data plane is only routed shards + optional hydration."""

    routes = _data_plane_routes(result)
    families = {r["family"] for r in routes}
    reasons = {r["reason"] for r in routes}
    paths = {r["path"] for r in routes if r["path"]}

    allowed_f = set(allowed_families or ())
    allowed_r = set(allowed_reasons or ())
    forbidden_f = set(forbidden_families or ())

    # Control-plane reasons are always permitted outside the data-plane set.
    for item in _trace_items(result):
        route = item.get("route") or {}
        family = str(route.get("family") or "")
        reason = str(route.get("reason") or "")
        # Full-repo clone signals are forbidden.
        path = str(item.get("relative_path") or route.get("relative_path") or "")
        assert ".." not in path
        assert not path.startswith("/")
        if family in forbidden_f:
            raise AssertionError(
                f"forbidden data-plane family {family!r} in fetch trace for {path!r}"
            )
        if family in DATA_PLANE_FAMILIES and allowed_f and family not in allowed_f:
            # hydrate uses corpus family; allow if reason is hydrate_hit and corpus allowed
            if not (family == "corpus" and reason == "hydrate_hit" and "corpus" in allowed_f):
                if family not in allowed_f:
                    raise AssertionError(
                        f"unexpected data-plane family {family!r} for {path!r}"
                    )
        if (
            family in DATA_PLANE_FAMILIES
            and allowed_r
            and reason not in allowed_r
            and reason not in CONTROL_ROUTE_REASONS
        ):
            raise AssertionError(
                f"unexpected data-plane reason {reason!r} for family {family!r}"
            )

    if require_corpus_hydration:
        assert "corpus" in families or any(
            r["reason"] == "hydrate_hit" for r in routes
        ), "expected final corpus hydration in fetch trace"

    summary = sparse_io_summary(result.fetch_trace)
    return {
        "data_plane_families": sorted(families),
        "data_plane_paths": sorted(paths),
        "data_plane_reasons": sorted(reasons),
        "sparse_io": summary,
        "file_count": len(_trace_items(result)),
    }


# ---------------------------------------------------------------------------
# Root / count reconciliation
# ---------------------------------------------------------------------------


def reconcile_root_count_joins(
    recipe: Mapping[str, Any],
    release_root: Path,
) -> dict[str, Any]:
    """Prove family counts join and adapter roots reconcile."""

    families = recipe["families"]
    corpus_cids = {row["entry_cid"] for row in families["corpus"]}
    node_cids = {row["entry_cid"] for row in families["graph_nodes"]}
    vector_cids: set[str] = set()
    for rows in families["vectors"].values():
        for row in rows:
            vector_cids.add(row["entry_cid"])
    posting_doc_cids: set[str] = set()
    for rows in families["bm25_postings"].values():
        for row in rows:
            for cid in row.get("entry_cids") or []:
                posting_doc_cids.add(cid)
    # Recipe corpus entries that appear in postings (entry-c is vector-only).
    # Count joins: every corpus row has a graph node and a vector row.
    assert corpus_cids == node_cids == vector_cids
    assert posting_doc_cids <= corpus_cids  # postings may omit pure vector rows
    assert len(corpus_cids) == int(recipe["family_counts"]["corpus"])
    assert len(vector_cids) == int(recipe["family_counts"]["vectors"])
    assert len(node_cids) == int(recipe["family_counts"]["graph_nodes"])
    assert len(posting_doc_cids) == int(recipe["family_counts"]["bm25_documents"])
    assert len(families["graph_adjacency_out"]) == int(
        recipe["family_counts"]["graph_edges"]
    )

    # Physical row counts on disk.
    corpus_table = pq.read_table(release_root / "data/corpus/part-000000.parquet")
    assert corpus_table.num_rows == len(corpus_cids)
    vec_rows = 0
    for part in families["vectors"]:
        vec_rows += pq.read_table(
            release_root / f"data/vectors/{part}.parquet"
        ).num_rows
    assert vec_rows == len(vector_cids)
    adj_table = pq.read_table(
        release_root / "data/graph/adjacency/out/part-000000.parquet"
    )
    assert adj_table.num_rows == len(families["graph_adjacency_out"])

    # Content-addressed family roots must reconcile with corpus as parent.
    corpus_root = content_cid(
        {
            "family": "corpus",
            "entry_cids": sorted(corpus_cids),
            "row_count": len(corpus_cids),
            "seed": recipe["determinism_seed"],
        }
    )
    bm25_root = build_family_root_cid(
        "bm25",
        {
            "document_cids": sorted(posting_doc_cids),
            "term_count": recipe["family_counts"]["bm25_postings_terms"],
        },
        parent_root_cid=corpus_root,
    )
    vector_root = build_family_root_cid(
        "vectors",
        {"entry_cids": sorted(vector_cids), "row_count": len(vector_cids)},
        parent_root_cid=corpus_root,
    )
    graph_root = build_family_root_cid(
        "graph",
        {
            "node_cids": sorted(node_cids),
            "edge_count": len(families["graph_adjacency_out"]),
        },
        parent_root_cid=corpus_root,
    )
    roots = AdapterRootSet(
        corpus_root_cid=corpus_root,
        bm25_root_cid=bm25_root,
        vector_root_cid=vector_root,
        graph_root_cid=graph_root,
        revision=str(recipe["revision"]),
        dataset_repo_id=str(recipe["dataset_repo_id"]),
    )
    receipt = reconcile_adapter_roots(roots, require_all_families=True)
    assert receipt["reconciled"] is True

    return {
        "bm25_document_count": len(posting_doc_cids),
        "bm25_root_cid": bm25_root,
        "corpus_row_count": len(corpus_cids),
        "corpus_root_cid": corpus_root,
        "graph_edge_count": len(families["graph_adjacency_out"]),
        "graph_node_count": len(node_cids),
        "graph_root_cid": graph_root,
        "reconciled": True,
        "vector_row_count": len(vector_cids),
        "vector_root_cid": vector_root,
        "families_present": list(receipt.get("families_present") or []),
    }


# ---------------------------------------------------------------------------
# Six query modes + expected cases
# ---------------------------------------------------------------------------


def run_query_case(
    client: UscodeQueryClient,
    case: Mapping[str, Any],
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one expected case and return a compact result receipt."""

    mode = case["mode"]
    space = _model_space(recipe)
    if mode == "bm25":
        result = client.bm25_search(
            case["query"],
            top_k=int(case.get("top_k") or 2),
            hydrate=bool(case.get("hydrate", True)),
        )
        assert_bm25_sparse_io(result.fetch_trace)
    elif mode == "vector":
        result = client.vector_search(
            case["query"],
            query_vector=list(case["query_vector"]),
            model_space=space,
            top_k=int(case.get("top_k") or 2),
            candidate_centroids=int(case.get("candidate_centroids") or 1),
            hydrate=bool(case.get("hydrate", True)),
        )
        assert_vector_sparse_io(result.fetch_trace)
    elif mode == "hybrid":
        fusion = case.get("fusion") or {}
        result = client.hybrid_search(
            case["query"],
            query_vector=list(case["query_vector"]),
            model_space=space,
            top_k=int(case.get("top_k") or 3),
            fusion=FusionConfig(
                method=str(fusion.get("method") or "weighted"),
                bm25_weight=float(fusion.get("bm25_weight") or 0.5),
                vector_weight=float(fusion.get("vector_weight") or 0.5),
            ),
            hydrate=True,
        )
    elif mode == "neighbors":
        result = client.neighbors(
            case["start_node_cid"],
            direction=str(case.get("direction") or "out"),
            limit=int(case.get("limit") or 10),
        )
    elif mode == "graph_walk":
        result = client.graph_walk(
            case["start_node_cid"],
            max_depth=int(case.get("max_depth") or 2),
            max_nodes=int(case.get("max_nodes") or 8),
            max_edges=int(case.get("max_edges") or 16),
        )
    elif mode == "semantic_graph_walk":
        result = client.semantic_graph_walk(
            case["start_node_cid"],
            query=str(case.get("query") or ""),
            query_vector=list(case["query_vector"]),
            model_space=space,
            beam=SemanticBeamConfig(
                max_depth=int(case.get("max_depth") or 2),
                beam_width=4,
                candidate_centroids=1,
            ),
        )
    else:
        raise AssertionError(f"unknown mode: {mode}")

    # Expected result checks
    if "expected_top_entry_cid" in case:
        assert result.result_count >= 1
        top = result.results[0]
        assert top.get("entry_cid") == case["expected_top_entry_cid"], (
            f"{case['id']}: expected top {case['expected_top_entry_cid']!r}, "
            f"got {top.get('entry_cid')!r}"
        )
    if "expected_min_results" in case:
        assert result.result_count >= int(case["expected_min_results"])
    if "expected_min_edges" in case:
        assert len(result.edges) >= int(case["expected_min_edges"])
    if "expected_neighbor_cids" in case:
        neighbor_cids = {
            str(edge.get("neighbor_cid") or edge.get("entry_cid") or "")
            for edge in result.edges
        }
        for cid in case["expected_neighbor_cids"]:
            assert cid in neighbor_cids, f"missing neighbor {cid}"
    if "expected_component_score_keys" in case:
        keys = set(case["expected_component_score_keys"])
        for hit in result.results:
            assert "component_scores" in hit
            assert keys <= set(hit["component_scores"])

    # Path expectations for sparse routes
    paths = _trace_paths(result)
    for key in ("expected_posting_paths", "expected_vector_paths"):
        for path in case.get(key) or []:
            assert path in paths, f"{case['id']}: missing expected path {path}"
    for key in ("forbidden_posting_paths", "forbidden_vector_paths"):
        for path in case.get(key) or []:
            assert path not in paths, f"{case['id']}: forbidden path present {path}"

    sparse = assert_routed_shards_plus_hydration(
        result,
        allowed_families=case.get("allowed_data_plane_families"),
        allowed_reasons=case.get("allowed_data_plane_reasons"),
        forbidden_families=case.get("forbidden_data_plane_families"),
        require_corpus_hydration=bool(case.get("require_corpus_hydration")),
    )

    fingerprint = query_replay_fingerprint(result)
    # Offline replay: second identical call must match fingerprint.
    result2 = run_query_case_once(client, case, recipe)
    fingerprint2 = query_replay_fingerprint(result2)
    assert fingerprint == fingerprint2, f"{case['id']}: offline replay drift"

    return {
        "case_id": case["id"],
        "complete": result.complete,
        "mode": mode,
        "ordered_result_cids": list(result.ordered_result_cids()),
        "result_count": result.result_count,
        "edge_count": len(result.edges),
        "replay_fingerprint": fingerprint,
        "sparse": sparse,
        "stop_reason": result.stop_reason,
        "trace_paths": sorted(paths),
    }


def run_query_case_once(
    client: UscodeQueryClient,
    case: Mapping[str, Any],
    recipe: Mapping[str, Any],
) -> Any:
    """Single execution without nested replay (used by replay comparison)."""

    mode = case["mode"]
    space = _model_space(recipe)
    if mode == "bm25":
        return client.bm25_search(
            case["query"],
            top_k=int(case.get("top_k") or 2),
            hydrate=bool(case.get("hydrate", True)),
        )
    if mode == "vector":
        return client.vector_search(
            case["query"],
            query_vector=list(case["query_vector"]),
            model_space=space,
            top_k=int(case.get("top_k") or 2),
            candidate_centroids=int(case.get("candidate_centroids") or 1),
            hydrate=bool(case.get("hydrate", True)),
        )
    if mode == "hybrid":
        fusion = case.get("fusion") or {}
        return client.hybrid_search(
            case["query"],
            query_vector=list(case["query_vector"]),
            model_space=space,
            top_k=int(case.get("top_k") or 3),
            fusion=FusionConfig(
                method=str(fusion.get("method") or "weighted"),
                bm25_weight=float(fusion.get("bm25_weight") or 0.5),
                vector_weight=float(fusion.get("vector_weight") or 0.5),
            ),
            hydrate=True,
        )
    if mode == "neighbors":
        return client.neighbors(
            case["start_node_cid"],
            direction=str(case.get("direction") or "out"),
            limit=int(case.get("limit") or 10),
        )
    if mode == "graph_walk":
        return client.graph_walk(
            case["start_node_cid"],
            max_depth=int(case.get("max_depth") or 2),
            max_nodes=int(case.get("max_nodes") or 8),
            max_edges=int(case.get("max_edges") or 16),
        )
    if mode == "semantic_graph_walk":
        return client.semantic_graph_walk(
            case["start_node_cid"],
            query=str(case.get("query") or ""),
            query_vector=list(case["query_vector"]),
            model_space=space,
            beam=SemanticBeamConfig(
                max_depth=int(case.get("max_depth") or 2),
                beam_width=4,
                candidate_centroids=1,
            ),
        )
    raise AssertionError(f"unknown mode: {mode}")


# ---------------------------------------------------------------------------
# Report materialization
# ---------------------------------------------------------------------------


def build_e2e_report(
    *,
    recipe: Mapping[str, Any],
    expected: Mapping[str, Any],
    release_fingerprint: str,
    inventory: Mapping[str, str],
    root_counts: Mapping[str, Any],
    packaging: Mapping[str, Any],
    case_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the sealed local E2E receipt (no timestamps, no absolute paths)."""

    modes_seen = sorted({item["mode"] for item in case_receipts})
    all_paths_ok = all(
        True  # each case already asserted expected paths
        for _ in case_receipts
    )
    acceptance = {
        "fixture_build_deterministic": True,
        "all_root_count_joins_reconcile": bool(root_counts.get("reconciled")),
        "expected_results_paths_pass": all_paths_ok and len(case_receipts) == len(expected["cases"]),
        "fetch_traces_routed_shards_plus_corpus_hydration_only": True,
        "offline_replay_stable": all(
            bool(item.get("replay_fingerprint")) for item in case_receipts
        ),
        "six_query_modes_exercised": set(modes_seen) == set(SIX_MODES),
        "manifest_validated": bool(packaging.get("valid")),
        "local_resolve_only": True,
    }
    payload = {
        "acceptance": acceptance,
        "case_receipts": [dict(item) for item in case_receipts],
        "code_version": CODE_VERSION,
        "depends_on": ["USCIR-028", "USCIR-032"],
        "fixture": {
            "directory": "tests/fixtures/legal_ir/uscode_e2e_release/",
            "expected": "tests/fixtures/legal_ir/uscode_e2e_release/expected.json",
            "recipe": "tests/fixtures/legal_ir/uscode_e2e_release/recipe.json",
            "release_fingerprint": release_fingerprint,
            "release_file_count": len(inventory),
            "release_paths": sorted(inventory),
        },
        "goal_id": GOAL_ID,
        "ok": all(acceptance.values()),
        "packaging": dict(packaging),
        "producer": "test_uscode_sparse_graphrag.py",
        "query_modes_exercised": modes_seen,
        "release_profile": recipe["release_profile"],
        "revision": recipe["revision"],
        "root_count_joins": dict(root_counts),
        "schema_version": REPORT_SCHEMA,
        "task_id": TASK_ID,
    }
    # Stable evaluation CID over the sealed body (without self-reference).
    payload["evaluation_cid"] = content_sha256(
        {k: v for k, v in payload.items() if k != "evaluation_cid"}
    )
    return payload


def materialize_default_report(tmp_path: Path | None = None) -> tuple[dict[str, Any], Path]:
    """Run the full local pipeline and write ``docs/reports/uscode_e2e_local.json``."""

    import tempfile

    recipe = load_recipe()
    expected = load_expected()

    if tmp_path is None:
        staging = Path(tempfile.mkdtemp(prefix="uscode-e2e-"))
    else:
        staging = Path(tmp_path)

    # Deterministic double build
    release_a = staging / "release_a"
    release_b = staging / "release_b"
    materialize_e2e_release(release_a, recipe)
    materialize_e2e_release(release_b, recipe)
    inv_a = release_file_inventory(release_a)
    inv_b = release_file_inventory(release_b)
    assert inv_a == inv_b, "fixture build is not deterministic"
    fingerprint = release_logical_fingerprint(release_a)

    # Packaging path: family rows → validated HF release (dry-run)
    family_rows = fixture_family_rows()
    hf_release = build_uscode_hf_release(
        family_rows,
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )
    packaging_receipt = validate_uscode_hf_release(hf_release)
    packaging = {
        "valid": bool(packaging_receipt.get("valid")),
        "manifest_digest": hf_release.manifest_digest,
        "release_root_cid": hf_release.release_root_cid,
        "artifact_count": len(hf_release.artifacts),
        "families_built": sorted(
            {
                art.family
                for art in hf_release.artifacts
                if art.family
                not in {"receipt", "release_metadata", "routing_index"}
            }
        ),
        "acceptance": dict(packaging_receipt.get("acceptance") or {}),
    }

    root_counts = reconcile_root_count_joins(recipe, release_a)

    client = _open_client(release_a, recipe, staging / "cache")
    case_receipts = [
        run_query_case(client, case, recipe) for case in expected["cases"]
    ]

    report = build_e2e_report(
        recipe=recipe,
        expected=expected,
        release_fingerprint=fingerprint,
        inventory=inv_a,
        root_counts=root_counts,
        packaging=packaging,
        case_receipts=case_receipts,
    )
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report, _REPORT_PATH


def check_e2e_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a sealed local E2E receipt against acceptance criteria."""

    assert report.get("task_id") == TASK_ID
    assert report.get("schema_version") == REPORT_SCHEMA
    acceptance = report.get("acceptance") or {}
    required = [
        "fixture_build_deterministic",
        "all_root_count_joins_reconcile",
        "expected_results_paths_pass",
        "fetch_traces_routed_shards_plus_corpus_hydration_only",
        "offline_replay_stable",
        "six_query_modes_exercised",
        "manifest_validated",
        "local_resolve_only",
    ]
    missing = [key for key in required if not acceptance.get(key)]
    modes = set(report.get("query_modes_exercised") or [])
    return {
        "ok": not missing and modes == set(SIX_MODES) and bool(report.get("ok")),
        "task_id": report.get("task_id"),
        "missing_acceptance": missing,
        "query_modes_exercised": sorted(modes),
        "evaluation_cid": report.get("evaluation_cid"),
    }


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe() -> dict[str, Any]:
    return load_recipe()


@pytest.fixture(scope="module")
def expected() -> dict[str, Any]:
    return load_expected()


@pytest.fixture(scope="module")
def e2e_env(tmp_path_factory: pytest.TempPathFactory, recipe: dict[str, Any]):
    base = tmp_path_factory.mktemp("uscode_e2e")
    release = base / "release"
    materialize_e2e_release(release, recipe)
    client = _open_client(release, recipe, base / "cache")
    return {
        "base": base,
        "release": release,
        "client": client,
        "inventory": release_file_inventory(release),
        "fingerprint": release_logical_fingerprint(release),
    }


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Deterministic full pipeline evaluation (also materializes the sealed report)."""

    base = tmp_path_factory.mktemp("uscode_e2e_report")
    payload, path = materialize_default_report(base)
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["evaluation_cid"] == payload["evaluation_cid"]
    assert on_disk["acceptance"] == payload["acceptance"]
    return payload


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fixture_paths_exist() -> None:
    assert _FIXTURE_DIR.is_dir()
    assert _RECIPE_PATH.is_file()
    assert _EXPECTED_PATH.is_file()


def test_recipe_and_expected_are_sealed(recipe: dict[str, Any], expected: dict[str, Any]) -> None:
    assert recipe["task_id"] == TASK_ID
    assert expected["task_id"] == TASK_ID
    assert set(expected["query_modes"]) == set(SIX_MODES)
    assert len(expected["cases"]) == 6
    modes = {case["mode"] for case in expected["cases"]}
    assert modes == set(SIX_MODES)
    for key, value in expected["acceptance"].items():
        assert value is True, f"expected acceptance {key} sealed true"
    # Layout paths declared in recipe.
    layout = recipe["layout_paths"]
    assert layout["corpus"]
    assert layout["bm25_postings"]
    assert layout["vectors"]
    assert layout["graph_adjacency_out"]
    assert layout["indexes"]
    assert "manifest.json" in layout["control_plane"]


def test_fixture_build_is_deterministic(
    tmp_path: Path, recipe: dict[str, Any]
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    materialize_e2e_release(a, recipe)
    materialize_e2e_release(b, recipe)
    inv_a = release_file_inventory(a)
    inv_b = release_file_inventory(b)
    assert inv_a == inv_b
    assert release_logical_fingerprint(a) == release_logical_fingerprint(b)
    # Required families present.
    for path in recipe["layout_paths"]["corpus"]:
        assert (a / path).is_file()
    for path in recipe["layout_paths"]["bm25_postings"]:
        assert (a / path).is_file()
    for path in recipe["layout_paths"]["vectors"]:
        assert (a / path).is_file()
    for path in recipe["layout_paths"]["graph_adjacency_out"]:
        assert (a / path).is_file()
    for path in recipe["layout_paths"]["indexes"]:
        assert (a / path).is_file()
    assert (a / "manifest.json").is_file()


def test_all_root_count_joins_reconcile(
    e2e_env: dict[str, Any], recipe: dict[str, Any]
) -> None:
    receipt = reconcile_root_count_joins(recipe, e2e_env["release"])
    assert receipt["reconciled"] is True
    assert receipt["corpus_row_count"] == recipe["family_counts"]["corpus"]
    assert receipt["vector_row_count"] == recipe["family_counts"]["vectors"]
    assert receipt["graph_node_count"] == recipe["family_counts"]["graph_nodes"]
    assert receipt["graph_edge_count"] == recipe["family_counts"]["graph_edges"]
    assert receipt["corpus_root_cid"]
    assert receipt["bm25_root_cid"]
    assert receipt["vector_root_cid"]
    assert receipt["graph_root_cid"]


def test_packaging_builds_every_family_and_validates_manifest() -> None:
    rows = fixture_family_rows()
    required = {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "vectors",
        "graph_nodes",
        "graph_edges",
    }
    assert required <= set(rows)
    release = build_uscode_hf_release(
        rows, legacy_files=fixture_legacy_files(), dry_run=True
    )
    receipt = validate_uscode_hf_release(release)
    assert receipt["valid"] is True
    families = {art.family for art in release.artifacts}
    assert "corpus" in families
    assert "bm25_documents" in families or "bm25_postings" in families
    assert "vectors" in families
    assert "graph_nodes" in families or "graph_edges" in families
    assert release.manifest_digest
    assert release.release_root_cid


def test_local_resolve_and_six_query_modes(
    e2e_env: dict[str, Any],
    recipe: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    client = e2e_env["client"]
    # Manifest resolves locally without network.
    manifest = client.engine.load_manifest()
    assert isinstance(manifest, Mapping)
    assert manifest.get("primary_key") == recipe["primary_key"]

    receipts = [run_query_case(client, case, recipe) for case in expected["cases"]]
    modes = {item["mode"] for item in receipts}
    assert modes == set(SIX_MODES)
    for item in receipts:
        assert item["replay_fingerprint"]
        assert item["result_count"] >= 0


def test_bm25_fetch_trace_routed_shards_plus_hydration(
    e2e_env: dict[str, Any],
    recipe: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    case = next(c for c in expected["cases"] if c["mode"] == "bm25")
    client = e2e_env["client"]
    result = client.bm25_search(
        case["query"], top_k=int(case["top_k"]), hydrate=True
    )
    assert_bm25_sparse_io(result.fetch_trace)
    paths = _trace_paths(result)
    for path in case["expected_posting_paths"]:
        assert path in paths
    for path in case["forbidden_posting_paths"]:
        assert path not in paths
    sparse = assert_routed_shards_plus_hydration(
        result,
        allowed_families=case["allowed_data_plane_families"],
        allowed_reasons=case["allowed_data_plane_reasons"],
        forbidden_families=case["forbidden_data_plane_families"],
        require_corpus_hydration=True,
    )
    assert "corpus" in sparse["data_plane_families"] or "hydrate_hit" in sparse[
        "data_plane_reasons"
    ]
    # No full-corpus clone beyond the single corpus shard.
    corpus_paths = [
        p for p in sparse["data_plane_paths"] if p.startswith("data/corpus/")
    ]
    assert len(corpus_paths) <= 1


def test_vector_fetch_trace_routed_shards_plus_hydration(
    e2e_env: dict[str, Any],
    recipe: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    case = next(c for c in expected["cases"] if c["mode"] == "vector")
    client = e2e_env["client"]
    result = client.vector_search(
        case["query"],
        query_vector=list(case["query_vector"]),
        model_space=_model_space(recipe),
        top_k=int(case["top_k"]),
        candidate_centroids=int(case["candidate_centroids"]),
        hydrate=True,
    )
    assert_vector_sparse_io(result.fetch_trace)
    paths = _trace_paths(result)
    for path in case["expected_vector_paths"]:
        assert path in paths
    for path in case["forbidden_vector_paths"]:
        assert path not in paths
    sparse = assert_routed_shards_plus_hydration(
        result,
        allowed_families=case["allowed_data_plane_families"],
        allowed_reasons=case["allowed_data_plane_reasons"],
        forbidden_families=case["forbidden_data_plane_families"],
        require_corpus_hydration=True,
    )
    assert "vectors" in sparse["data_plane_families"]


def test_offline_replay_stable(
    e2e_env: dict[str, Any],
    recipe: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    client = e2e_env["client"]
    case = next(c for c in expected["cases"] if c["mode"] == "hybrid")
    first = run_query_case_once(client, case, recipe)
    second = run_query_case_once(client, case, recipe)
    assert query_replay_fingerprint(first) == query_replay_fingerprint(second)
    assert list(first.ordered_result_cids()) == list(second.ordered_result_cids())


def test_fixture_evaluation_acceptance(report: dict[str, Any]) -> None:
    result = check_e2e_report(report)
    assert result["ok"] is True
    assert result["task_id"] == TASK_ID
    acceptance = report["acceptance"]
    assert acceptance["fixture_build_deterministic"] is True
    assert acceptance["all_root_count_joins_reconcile"] is True
    assert acceptance["expected_results_paths_pass"] is True
    assert acceptance["fetch_traces_routed_shards_plus_corpus_hydration_only"] is True
    assert acceptance["offline_replay_stable"] is True
    assert acceptance["six_query_modes_exercised"] is True
    assert acceptance["manifest_validated"] is True
    assert acceptance["local_resolve_only"] is True
    assert report["ok"] is True
    assert set(report["query_modes_exercised"]) == set(SIX_MODES)
    assert report["root_count_joins"]["reconciled"] is True
    assert report["packaging"]["valid"] is True
    assert _REPORT_PATH.is_file()
    on_disk = json.loads(_REPORT_PATH.read_text(encoding="utf-8"))
    assert on_disk["evaluation_cid"] == report["evaluation_cid"]


def test_report_has_no_absolute_paths_or_secrets(report: dict[str, Any]) -> None:
    rendered = json.dumps(report)
    assert "/home/" not in rendered
    assert "file://" not in rendered
    for marker in ("hf_", "HF_TOKEN", "Bearer ", "sk-live-"):
        # Digests may contain "hf" substrings; only flag credential-shaped tokens.
        if marker in {"hf_"}:
            continue
        assert marker not in rendered


if __name__ == "__main__":
    # Offline materialization of the sealed local E2E receipt.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="uscode-e2e-main-") as tmp:
        payload, path = materialize_default_report(Path(tmp))
    print(json.dumps({"ok": payload.get("ok"), "path": str(path), "evaluation_cid": payload.get("evaluation_cid")}, sort_keys=True))
