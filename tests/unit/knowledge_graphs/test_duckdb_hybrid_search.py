"""Unit tests for bounded DuckDB hybrid search (DQK-024).

Acceptance coverage:

* Results bind graph and vector generations
* Query budgets prevent control-plane starvation
* Legacy hybrid results meet declared differential thresholds
* Graph predicates, exact/approx vectors, text ranking, provenance, and
  revision filters operate without intermediate JSON serialization on the
  search hot path
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.query.duckdb_hybrid_search import (
    DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD,
    DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD,
    DEFAULT_RESERVED_CONTROL_PLANE_MS,
    DUCKDB_HYBRID_SEARCH_SCHEMA,
    DifferentialReport,
    DuckDBHybridSearch,
    DuckDBHybridSearchError,
    GraphPredicate,
    HybridHit,
    HybridQuery,
    HybridQueryBudget,
    HybridSearchResponse,
    ProvenanceFilter,
    RevisionFilter,
    TextQuery,
    VectorMode,
    VectorQuery,
    compare_legacy_hybrid_results,
    create_duckdb_hybrid_search,
    legacy_hybrid_fuse,
    text_rank_score,
)
from ipfs_datasets_py.vector_stores.duckdb_exact import ExactVectorStore
from ipfs_datasets_py.vector_stores.duckdb_vss import VSSIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def exact(tmp_path: Path) -> ExactVectorStore:
    store = ExactVectorStore(tmp_path / "exact.duckdb")
    store.create_collection("col", dimension=3, generation_id=7)
    store.upsert_vector("col", "n1", [1.0, 0.0, 0.0], metadata={"tag": "alpha"})
    store.upsert_vector("col", "n2", [0.0, 1.0, 0.0], metadata={"tag": "beta"})
    store.upsert_vector("col", "n3", [0.9, 0.1, 0.0], metadata={"tag": "alpha"})
    yield store
    store.close()


@pytest.fixture
def hybrid(tmp_path: Path, exact: ExactVectorStore) -> DuckDBHybridSearch:
    eng = DuckDBHybridSearch(tmp_path / "hybrid.duckdb", exact_store=exact)
    # Graph revision R1 / generation 3
    eng.upsert_vertex(
        "n1",
        graph_revision="rev-R1",
        graph_generation_id=3,
        node_type="Entity",
        name="IPFS protocol",
        source_text="content addressed peer to peer hypermedia",
        source_cid="bafy1",
        tenant="t1",
        provenance_kind="extract",
        labels=["Entity", "Protocol"],
        properties={"domain": "storage"},
    )
    eng.upsert_vertex(
        "n2",
        graph_revision="rev-R1",
        graph_generation_id=3,
        node_type="Entity",
        name="BitTorrent",
        source_text="peer to peer file sharing protocol",
        source_cid="bafy2",
        tenant="t1",
        provenance_kind="extract",
        labels=["Entity"],
        properties={"domain": "p2p"},
    )
    eng.upsert_vertex(
        "n3",
        graph_revision="rev-R1",
        graph_generation_id=3,
        node_type="Concept",
        name="content addressing",
        source_text="hash based content identifiers CIDs",
        source_cid="bafy1",
        tenant="t1",
        provenance_kind="manual",
        labels=["Concept"],
        properties={"domain": "storage"},
    )
    eng.upsert_vertex(
        "n4",
        graph_revision="rev-R2",
        graph_generation_id=4,
        node_type="Entity",
        name="other revision node",
        source_text="should be filtered by revision",
        source_cid="bafy9",
        tenant="t2",
        provenance_kind="extract",
        labels=["Entity"],
        properties={"domain": "other"},
    )
    eng.upsert_edge(
        "e1",
        source_id="n1",
        target_id="n3",
        edge_type="RELATED_TO",
        graph_revision="rev-R1",
        graph_generation_id=3,
    )
    eng.upsert_edge(
        "e2",
        source_id="n1",
        target_id="n2",
        edge_type="SIMILAR_TO",
        graph_revision="rev-R1",
        graph_generation_id=3,
    )
    yield eng
    eng.close()


def _full_query(**overrides: Any) -> HybridQuery:
    base: Dict[str, Any] = {
        "k": 5,
        "graph": GraphPredicate(
            node_types=("Entity", "Concept"),
            max_hops=1,
            edge_types=("RELATED_TO", "SIMILAR_TO"),
        ),
        "vector": VectorQuery(
            collection_id="col",
            query_vector=(1.0, 0.0, 0.0),
            k=5,
            metric="l2",
            mode=VectorMode.EXACT,
            generation_id=7,
            weight=0.5,
        ),
        "text": TextQuery(query="content addressing peer", weight=0.25),
        "provenance": ProvenanceFilter(tenants=("t1",)),
        "revision": RevisionFilter(
            graph_revisions=("rev-R1",),
            graph_generation_ids=(3,),
            require_bound_generations=True,
        ),
        "graph_weight": 0.25,
        "measure_legacy_differential": True,
    }
    base.update(overrides)
    return HybridQuery(**base)


# ---------------------------------------------------------------------------
# Acceptance: Results bind graph and vector generations
# ---------------------------------------------------------------------------


def test_results_bind_graph_and_vector_generations(
    hybrid: DuckDBHybridSearch,
) -> None:
    response = hybrid.search(_full_query())
    assert isinstance(response, HybridSearchResponse)
    assert response.schema == DUCKDB_HYBRID_SEARCH_SCHEMA
    assert response.graph_revision == "rev-R1"
    assert response.graph_generation_id == 3
    assert response.vector_collection_id == "col"
    assert response.vector_generation_id == 7
    assert response.hits
    for hit in response.hits:
        assert isinstance(hit, HybridHit)
        assert hit.graph_revision == "rev-R1"
        assert hit.graph_generation_id == 3
        # Vector-backed hits must carry generation + digest bindings.
        if hit.vector_score > 0:
            assert hit.vector_generation_id == 7
            assert hit.content_digest.startswith("sha256:")
            assert hit.vector_collection_id == "col"
    # Revision filter excluded n4 (rev-R2).
    assert all(h.node_id != "n4" for h in response.hits)
    # Digest is stable over native fields.
    d1 = hybrid.result_digest(response)
    d2 = hybrid.result_digest(response)
    assert d1 == d2
    assert d1.startswith("sha256:")


def test_vector_generation_mismatch_fails_closed(
    hybrid: DuckDBHybridSearch,
) -> None:
    q = _full_query(
        vector=VectorQuery(
            collection_id="col",
            query_vector=(1.0, 0.0, 0.0),
            k=3,
            generation_id=999,  # store is on gen 7
            mode=VectorMode.EXACT,
        )
    )
    with pytest.raises(DuckDBHybridSearchError) as exc:
        hybrid.search(q)
    assert exc.value.code in {"GENERATION", "VECTOR"}


# ---------------------------------------------------------------------------
# Acceptance: Query budgets prevent control-plane starvation
# ---------------------------------------------------------------------------


def test_reserved_control_plane_capacity_is_explicit() -> None:
    budget = HybridQueryBudget(
        max_time_ms=1000,
        reserved_control_plane_ms=250,
        max_nodes=100,
        max_edges=100,
        max_rows=50,
        max_vector_candidates=50,
    )
    assert budget.reserved_control_plane_ms == DEFAULT_RESERVED_CONTROL_PLANE_MS
    assert budget.analytical_time_ms == 750
    assert budget.analytical_time_ms < budget.max_time_ms
    # Cannot reserve the entire window.
    with pytest.raises(DuckDBHybridSearchError) as exc:
        HybridQueryBudget(max_time_ms=100, reserved_control_plane_ms=100)
    assert exc.value.code == "BUDGET"


def test_node_budget_prevents_unbounded_scan(
    hybrid: DuckDBHybridSearch,
) -> None:
    tight = HybridQueryBudget(
        max_time_ms=5_000,
        reserved_control_plane_ms=500,
        max_nodes=1,  # load of 3 matching vertices exceeds this
        max_edges=10_000,
        max_rows=10,
        max_vector_candidates=100,
    )
    q = _full_query(budget=tight, measure_legacy_differential=False)
    with pytest.raises(DuckDBHybridSearchError) as exc:
        hybrid.search(q)
    assert exc.value.code == "BUDGET_EXCEEDED"
    assert "nodes" in str(exc.value).lower() or "node" in str(exc.value).lower()
    # Analytical limit leaves control-plane headroom.
    assert tight.analytical_time_ms == 4_500
    assert tight.reserved_control_plane_ms == 500


def test_vector_candidate_budget(
    hybrid: DuckDBHybridSearch,
) -> None:
    tight = HybridQueryBudget(
        max_time_ms=5_000,
        reserved_control_plane_ms=200,
        max_nodes=10_000,
        max_edges=10_000,
        max_rows=10,
        max_vector_candidates=0,  # any vector hit exceeds
    )
    q = HybridQuery(
        k=3,
        vector=VectorQuery(
            collection_id="col",
            query_vector=(1.0, 0.0, 0.0),
            k=3,
            generation_id=7,
        ),
        revision=RevisionFilter(require_bound_generations=False),
        budget=tight,
    )
    with pytest.raises(DuckDBHybridSearchError) as exc:
        hybrid.search(q)
    assert exc.value.code == "BUDGET_EXCEEDED"


def test_response_reports_reserved_control_plane(
    hybrid: DuckDBHybridSearch,
) -> None:
    budget = HybridQueryBudget(
        max_time_ms=2_000,
        reserved_control_plane_ms=300,
        max_nodes=10_000,
        max_edges=10_000,
        max_rows=10,
        max_vector_candidates=100,
    )
    response = hybrid.search(_full_query(budget=budget))
    assert response.reserved_control_plane_ms == 300
    assert response.analytical_time_ms == 1_700
    assert response.elapsed_ms <= response.analytical_time_ms
    assert response.budget_exhausted is False


# ---------------------------------------------------------------------------
# Acceptance: Legacy hybrid results meet declared differential thresholds
# ---------------------------------------------------------------------------


def test_differential_thresholds_are_explicit_constants() -> None:
    assert DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD == 0.8
    assert DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD == 0.7
    assert 0.0 < DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD <= 1.0
    assert 0.0 < DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD <= 1.0


def test_legacy_hybrid_meets_differential_thresholds(
    hybrid: DuckDBHybridSearch,
) -> None:
    response = hybrid.search(_full_query(measure_legacy_differential=True))
    assert response.differential is not None
    report = response.differential
    assert isinstance(report, DifferentialReport)
    assert report.overlap_threshold == DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD
    assert (
        report.rank_agreement_threshold
        == DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD
    )
    assert report.meets_thresholds is True
    assert report.overlap_ratio + 1e-12 >= report.overlap_threshold
    assert report.rank_agreement + 1e-12 >= report.rank_agreement_threshold
    assert report.k == 5
    assert report.hybrid_ids
    assert report.legacy_ids


def test_compare_legacy_detects_divergence() -> None:
    report = compare_legacy_hybrid_results(
        ["a", "b", "c", "d", "e"],
        ["x", "y", "z", "w", "v"],
        k=5,
    )
    assert report.meets_thresholds is False
    assert report.overlap_ratio == 0.0


def test_legacy_fuse_deterministic_order() -> None:
    ranked = legacy_hybrid_fuse(
        {"a": 0.9, "b": 0.5},
        {"a": 0, "c": 1},
        vector_weight=0.6,
        graph_weight=0.4,
        k=10,
    )
    ids = [r[0] for r in ranked]
    assert ids[0] == "a"
    assert "c" in ids
    # Re-run is stable.
    ranked2 = legacy_hybrid_fuse(
        {"a": 0.9, "b": 0.5},
        {"a": 0, "c": 1},
        vector_weight=0.6,
        graph_weight=0.4,
        k=10,
    )
    assert ranked == ranked2


# ---------------------------------------------------------------------------
# Graph predicates, text ranking, provenance, revision filters
# ---------------------------------------------------------------------------


def test_graph_type_and_property_predicates(
    hybrid: DuckDBHybridSearch,
) -> None:
    q = HybridQuery(
        k=10,
        graph=GraphPredicate(
            node_types=("Entity",),
            property_equals=(("domain", "storage"),),
            max_hops=0,
        ),
        revision=RevisionFilter(
            graph_revisions=("rev-R1",),
            require_bound_generations=True,
        ),
        graph_weight=1.0,
    )
    response = hybrid.search(q)
    ids = {h.node_id for h in response.hits}
    assert "n1" in ids
    assert "n2" not in ids  # domain=p2p
    assert "n3" not in ids  # Concept, not Entity
    assert "n4" not in ids  # wrong revision


def test_provenance_filter(hybrid: DuckDBHybridSearch) -> None:
    q = HybridQuery(
        k=10,
        graph=GraphPredicate(max_hops=0),
        provenance=ProvenanceFilter(
            source_cids=("bafy1",),
            provenance_kinds=("extract",),
        ),
        revision=RevisionFilter(graph_revisions=("rev-R1",)),
        graph_weight=1.0,
    )
    response = hybrid.search(q)
    assert {h.node_id for h in response.hits} == {"n1"}
    assert all(h.source_cid == "bafy1" for h in response.hits)
    assert all(h.provenance_kind == "extract" for h in response.hits)


def test_text_ranking_prefers_relevant_nodes(
    hybrid: DuckDBHybridSearch,
) -> None:
    q = HybridQuery(
        k=3,
        text=TextQuery(query="content addressing CID", weight=1.0),
        revision=RevisionFilter(graph_revisions=("rev-R1",)),
    )
    response = hybrid.search(q)
    assert response.hits
    # n3 name/source_text is about content addressing.
    assert response.hits[0].node_id == "n3"
    assert response.hits[0].text_score > 0
    assert text_rank_score("content", "content addressed") > 0


def test_graph_expansion_hop_distances(
    hybrid: DuckDBHybridSearch,
) -> None:
    q = HybridQuery(
        k=10,
        graph=GraphPredicate(
            seed_node_ids=("n1",),
            max_hops=1,
            edge_types=("RELATED_TO",),
        ),
        revision=RevisionFilter(graph_revisions=("rev-R1",)),
        graph_weight=1.0,
    )
    response = hybrid.search(q)
    hops = {h.node_id: h.hop_distance for h in response.hits}
    assert hops.get("n1") == 0
    assert hops.get("n3") == 1
    # SIMILAR_TO edge excluded by edge_types filter → n2 not expanded.
    assert "n2" not in hops or hops["n2"] == 0 and "n2" in q.graph.seed_node_ids


def test_approx_vector_path_with_vss(
    tmp_path: Path, exact: ExactVectorStore
) -> None:
    vss = VSSIndex(
        exact=exact,
        collection_id="col",
        dimension=3,
        generation_id=7,
        extension_probe=lambda: True,
    )
    vss.build(
        {
            "n1": [1.0, 0.0, 0.0],
            "n2": [0.0, 1.0, 0.0],
            "n3": [0.9, 0.1, 0.0],
        }
    )
    eng = create_duckdb_hybrid_search(
        tmp_path / "hybrid_vss.duckdb",
        exact_store=exact,
        vss_index=vss,
    )
    eng.upsert_vertex(
        "n1",
        graph_revision="rev-R1",
        graph_generation_id=3,
        node_type="Entity",
        name="a",
        source_cid="c1",
    )
    eng.upsert_vertex(
        "n2",
        graph_revision="rev-R1",
        graph_generation_id=3,
        node_type="Entity",
        name="b",
        source_cid="c2",
    )
    eng.upsert_vertex(
        "n3",
        graph_revision="rev-R1",
        graph_generation_id=3,
        node_type="Entity",
        name="c",
        source_cid="c3",
    )
    try:
        response = eng.search(
            HybridQuery(
                k=2,
                vector=VectorQuery(
                    collection_id="col",
                    query_vector=(1.0, 0.0, 0.0),
                    k=2,
                    mode=VectorMode.AUTO,
                    generation_id=7,
                ),
                revision=RevisionFilter(
                    graph_revisions=("rev-R1",),
                    require_bound_generations=True,
                ),
            )
        )
        assert response.hits[0].node_id == "n1"
        assert response.vector_generation_id == 7
        assert response.graph_generation_id == 3
    finally:
        eng.close()


# ---------------------------------------------------------------------------
# No intermediate JSON serialization on the hot path
# ---------------------------------------------------------------------------


def test_search_path_does_not_json_serialize_candidates(
    hybrid: DuckDBHybridSearch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fusion/ranking must not dump intermediate candidates via json.dumps."""

    original_dumps = json.dumps
    call_sites: List[str] = []

    def _guarded_dumps(obj: Any, *args: Any, **kwargs: Any) -> str:
        # Allow accidental imports; fail if hybrid_search module invokes dumps
        # during search.
        import traceback

        stack = traceback.format_stack()
        if any("duckdb_hybrid_search.py" in frame for frame in stack):
            call_sites.append("json.dumps")
        return original_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(json, "dumps", _guarded_dumps)
    response = hybrid.search(_full_query(measure_legacy_differential=True))
    assert response.hits
    assert call_sites == [], f"unexpected json.dumps on hot path: {call_sites}"
    # Results are native dataclasses, not JSON strings.
    assert isinstance(response.hits[0], HybridHit)
    assert isinstance(response.hits[0].score, float)


def test_properties_stored_as_native_maps_not_json_blobs(
    hybrid: DuckDBHybridSearch,
) -> None:
    # Property filters use native maps; storage table has no properties_json.
    cols = hybrid._conn.execute(  # noqa: SLF001 — intentional schema check
        "DESCRIBE hybrid_vertices"
    ).fetchall()
    col_names = {str(c[0]).lower() for c in cols}
    assert "properties_json" not in col_names
    assert "node_id" in col_names
    assert "graph_revision" in col_names
    assert "graph_generation_id" in col_names
    # Native property map still supports filtering.
    assert hybrid._properties["n1"]["domain"] == "storage"  # noqa: SLF001


def test_factory_and_context_manager(tmp_path: Path, exact: ExactVectorStore) -> None:
    with create_duckdb_hybrid_search(
        tmp_path / "ctx.duckdb", exact_store=exact
    ) as eng:
        eng.upsert_vertex(
            "x",
            graph_revision="r",
            graph_generation_id=1,
            name="hello world",
            source_text="hello",
        )
        resp = eng.search(
            HybridQuery(
                k=1,
                text=TextQuery(query="hello"),
                revision=RevisionFilter(require_bound_generations=True),
            )
        )
        assert resp.hits[0].node_id == "x"
        assert resp.hits[0].graph_generation_id == 1


def test_search_simple_convenience(hybrid: DuckDBHybridSearch) -> None:
    resp = hybrid.search_simple(
        k=3,
        query_vector=[1.0, 0.0, 0.0],
        collection_id="col",
        text="IPFS",
        graph_revision="rev-R1",
        max_hops=1,
    )
    assert resp.hits
    assert resp.vector_generation_id == 7
    assert resp.graph_revision == "rev-R1"
    assert resp.differential is not None
