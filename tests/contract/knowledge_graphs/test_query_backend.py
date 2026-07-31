"""KGP-015: Consolidate one GraphQueryBackend and executor.

Acceptance coverage:
* One target-bound protocol implements scans, lookup, neighbors, paths,
  Cypher IR, hybrid/vector and explicit federation.
* Local Parquet and sharded IPFS return canonical equivalent rows.
* Distributed execution uses declared targets, never a newly constructed
  empty KnowledgeGraph.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from ipfs_datasets_py.knowledge_graphs.query.backend import (
    BACKEND_API_VERSION,
    CANONICAL_EDGE_COLUMNS,
    CANONICAL_NODE_COLUMNS,
    Expand,
    FederatedGraphQueryBackend,
    GraphQueryBackend,
    GraphQueryBackendError,
    InMemoryGraphQueryBackend,
    Limit,
    ParquetGraphQueryBackend,
    Project,
    QueryIR,
    ScanType,
    SeedEntities,
    ShardedIPFSGraphQueryBackend,
    canonical_edge_row,
    canonical_node_row,
    open_federated_backend,
    open_memory_backend,
    open_parquet_backend,
    open_sharded_ipfs_backend,
    rows_equal,
    sort_edge_rows,
    sort_node_rows,
)
from ipfs_datasets_py.knowledge_graphs.query.executor import (
    GraphQueryExecutor,
    LegacyGraphBackendAdapter,
    build_simple_ir,
)
from ipfs_datasets_py.knowledge_graphs.service import GraphTarget

pyarrow = pytest.importorskip("pyarrow")


# ---------------------------------------------------------------------------
# Shared sample graph
# ---------------------------------------------------------------------------


def _sample_nodes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "n1",
            "type": "Person",
            "name": "Alice",
            "properties": {"age": 30, "city": "SF"},
        },
        {
            "id": "n2",
            "type": "Org",
            "name": "Acme",
            "properties": {"city": "SF"},
        },
        {
            "id": "n3",
            "type": "Person",
            "name": "Bob",
            "properties": {"age": 25},
        },
        {
            "id": "n4",
            "type": "Person",
            "name": "Carol",
            "properties": {"age": 28},
        },
    ]


def _sample_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e1",
            "type": "WORKS_AT",
            "source_id": "n1",
            "target_id": "n2",
            "properties": {"since": 2020},
        },
        {
            "id": "e2",
            "type": "KNOWS",
            "source_id": "n1",
            "target_id": "n3",
        },
        {
            "id": "e3",
            "type": "KNOWS",
            "source_id": "n3",
            "target_id": "n4",
        },
    ]


def _target(
    tenant: str = "acme",
    graph_id: str = "skills",
    revision: str = "rev-001",
    storage_profile: str = "parquet",
) -> GraphTarget:
    return GraphTarget(
        tenant=tenant,
        graph_id=graph_id,
        branch=None,
        revision=revision,
        storage_profile=storage_profile,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_backend() -> InMemoryGraphQueryBackend:
    return open_memory_backend(
        _target(storage_profile="hybrid"),
        nodes=_sample_nodes(),
        edges=_sample_edges(),
        revision="rev-001",
    )


@pytest.fixture
def parquet_backend(tmp_path):
    from ipfs_datasets_py.knowledge_graphs.storage.parquet import ParquetGraphStore

    store = ParquetGraphStore.open(tmp_path / "parquet-store", row_group_size=8)
    store.publish_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        nodes=_sample_nodes(),
        edges=_sample_edges(),
        provenance={
            "producer_id": "kgp-015-tests",
            "producer_version": "1",
            "source": "contract",
            "created_at": "2026-07-29T00:00:00Z",
        },
    )
    backend = open_parquet_backend(
        _target(storage_profile="parquet"),
        store,
        revision_id="rev-001",
    )
    try:
        yield backend, store
    finally:
        store.close()


@pytest.fixture
def sharded_backend():
    from ipfs_datasets_py.knowledge_graphs.storage.sharding.models import GraphFragment
    from ipfs_datasets_py.knowledge_graphs.storage.sharding.publish import (
        publish_sharded_graph_v2,
    )

    g = GraphFragment(name="skills")
    for n in _sample_nodes():
        g.add_entity(
            entity_id=n["id"],
            entity_type=n["type"],
            name=n["name"],
            properties=n.get("properties") or {},
        )
    for e in _sample_edges():
        g.add_relationship(
            relationship_id=e["id"],
            relationship_type=e["type"],
            source_id=e["source_id"],
            target_id=e["target_id"],
            properties=e.get("properties") or {},
        )
    published = publish_sharded_graph_v2(
        g,
        num_physical_shards=2,
        virtual_shard_count=16,
        seed="kgp-015-parity",
        index_bucket_target_size=8,
        force_bucket_prefix_len=1,
    )
    target = _target(
        revision=published.manifest.root_cid or "rev-sharded",
        storage_profile="ipfs_ipld",
    )
    backend = open_sharded_ipfs_backend(
        target,
        published=published,
        revision=published.manifest.root_cid,
    )
    return backend, published


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------


def test_backend_api_version_constant() -> None:
    assert BACKEND_API_VERSION.startswith("kg-graph-query-backend/")
    assert set(CANONICAL_NODE_COLUMNS) >= {"id", "type", "name", "properties"}
    assert set(CANONICAL_EDGE_COLUMNS) >= {
        "source_id",
        "target_id",
        "relationship_type",
    }


def test_inmemory_is_graph_query_backend(memory_backend) -> None:
    assert isinstance(memory_backend, GraphQueryBackend)
    assert memory_backend.target.tenant == "acme"
    assert memory_backend.target.graph_id == "skills"
    assert memory_backend.revision == "rev-001"


def test_requires_explicit_target() -> None:
    with pytest.raises(GraphQueryBackendError) as ei:
        InMemoryGraphQueryBackend(None, nodes=_sample_nodes())  # type: ignore[arg-type]
    assert ei.value.code == "INVALID_TARGET"


def test_canonical_row_helpers() -> None:
    n = canonical_node_row(
        entity_id="x",
        entity_type="Person",
        name="X",
        properties={"k": 1},
    )
    assert n["id"] == "x"
    assert n["properties"]["k"] == 1
    e = canonical_edge_row(
        source_id="a",
        target_id="b",
        relationship_type="KNOWS",
        relationship_id="r1",
    )
    assert e["source_id"] == "a"
    assert e["direction"] == "outgoing"


# ---------------------------------------------------------------------------
# Core ops on in-memory backend
# ---------------------------------------------------------------------------


def test_scan_lookup_neighbors_paths(memory_backend) -> None:
    scanned = memory_backend.scan(limit=100)
    assert len(scanned.rows) == 4
    assert all(set(CANONICAL_NODE_COLUMNS) <= set(r.keys()) for r in scanned.rows)

    persons = memory_backend.scan(entity_type="Person")
    assert {r["id"] for r in persons.rows} == {"n1", "n3", "n4"}

    found = memory_backend.lookup(["n1", "missing", "n2"])
    assert [r["id"] for r in found.rows] == ["n1", "n2"]
    assert found.statistics["found"] == 2

    nbr = memory_backend.neighbors("n1", direction="outgoing")
    types = {r["relationship_type"] for r in nbr.rows}
    assert types == {"WORKS_AT", "KNOWS"}
    assert all(r["source_id"] == "n1" for r in nbr.rows)

    paths = memory_backend.paths("n1", max_depth=2, limit=50)
    assert paths.statistics["path_count"] >= 1
    # Alice -> Bob -> Carol is a length-2 path
    node_seqs = [tuple(p["node_ids"]) for p in paths.rows]
    assert any(seq == ("n1", "n3", "n4") or list(seq) == ["n1", "n3", "n4"] for seq in node_seqs)


def test_cypher_ir_scan_expand_project(memory_backend) -> None:
    ir = (
        QueryIR()
        .add(ScanType(entity_type="Person"))
        .add(Expand(relationship_types=["KNOWS"], direction="outgoing"))
        .add(Limit(10))
        .add(Project(fields=("id", "type", "name")))
    )
    result = memory_backend.execute_ir(ir, budgets={"allow_unanchored_scan": True})
    assert result.stats["returned"] >= 1
    ids = {item["id"] for item in result.items}
    # Expanding KNOWS from Person seeds: n1->n3, n3->n4
    assert "n3" in ids or "n4" in ids


def test_seed_ir(memory_backend) -> None:
    ir = QueryIR.from_ops(
        [
            SeedEntities(["n1", "nope"]),
            Project(fields=("id", "name")),
        ]
    )
    result = memory_backend.execute_ir(ir)
    assert len(result.items) == 1
    assert result.items[0]["id"] == "n1"


def test_hybrid_and_vector_search(memory_backend) -> None:
    from ipfs_datasets_py.knowledge_graphs.query.backend import _text_embedding

    qvec = _text_embedding("Alice Person")
    vec = memory_backend.vector_search(qvec, k=3)
    assert len(vec.rows) == 3
    assert vec.rows[0]["id"] in {"n1", "n2", "n3", "n4"}
    assert "score" in vec.rows[0]

    hybrid = memory_backend.hybrid_search("Alice Acme", k=3, max_hops=1)
    assert len(hybrid.rows) <= 3
    assert hybrid.schema == "kg-hybrid-hit/v1"
    assert all("vector_score" in r and "graph_score" in r for r in hybrid.rows)


# ---------------------------------------------------------------------------
# Parquet backend
# ---------------------------------------------------------------------------


def test_parquet_backend_ops(parquet_backend) -> None:
    backend, _store = parquet_backend
    assert isinstance(backend, ParquetGraphQueryBackend)
    assert isinstance(backend, GraphQueryBackend)

    nodes = sort_node_rows(backend.scan(limit=100).rows)
    assert len(nodes) == 4
    assert {n["id"] for n in nodes} == {"n1", "n2", "n3", "n4"}
    alice = next(n for n in nodes if n["id"] == "n1")
    assert alice["type"] == "Person"
    assert alice["properties"]["age"] == 30

    edges = backend.neighbors("n1", direction="both")
    assert len(edges.rows) >= 2

    paths = backend.paths("n1", max_depth=1)
    assert paths.statistics["path_count"] >= 1


# ---------------------------------------------------------------------------
# Sharded IPFS backend
# ---------------------------------------------------------------------------


def test_sharded_ipfs_backend_ops(sharded_backend) -> None:
    backend, _published = sharded_backend
    assert isinstance(backend, ShardedIPFSGraphQueryBackend)
    assert isinstance(backend, GraphQueryBackend)

    nodes = sort_node_rows(backend.scan(limit=100).rows)
    assert len(nodes) == 4
    alice = next(n for n in nodes if n["id"] == "n1")
    assert alice["name"] == "Alice"
    assert alice["properties"]["city"] == "SF"

    nbr = backend.neighbors("n1", direction="outgoing")
    assert len(nbr.rows) >= 2
    targets = {r["target_id"] for r in nbr.rows}
    assert "n2" in targets
    assert "n3" in targets


# ---------------------------------------------------------------------------
# Canonical parity: Parquet vs sharded IPFS
# ---------------------------------------------------------------------------


def test_parquet_and_sharded_return_canonical_equivalent_rows(
    parquet_backend, sharded_backend
) -> None:
    p_backend, _ = parquet_backend
    s_backend, _ = sharded_backend

    p_nodes = sort_node_rows(p_backend.scan(limit=1000).rows)
    s_nodes = sort_node_rows(s_backend.scan(limit=1000).rows)

    # Drop cid for comparison (Parquet may not store entity CIDs).
    def strip_cid(rows):
        out = []
        for r in rows:
            d = dict(r)
            d["cid"] = None
            # Normalize empty name
            if d.get("name") == "":
                d["name"] = None
            out.append(d)
        return out

    assert rows_equal(strip_cid(p_nodes), strip_cid(s_nodes), kind="node")

    p_edges = sort_edge_rows(
        p_backend.neighbors("n1", direction="outgoing", limit=1000).rows
    )
    s_edges = sort_edge_rows(
        s_backend.neighbors("n1", direction="outgoing", limit=1000).rows
    )

    def edge_key_set(rows):
        return {
            (
                r["source_id"],
                r["target_id"],
                r["relationship_type"],
                r["relationship_id"],
            )
            for r in rows
        }

    assert edge_key_set(p_edges) == edge_key_set(s_edges)

    # Full edge inventory parity
    p_all = sort_edge_rows(list(p_backend._iter_edges()))
    s_all = sort_edge_rows(list(s_backend._iter_edges()))
    assert edge_key_set(p_all) == edge_key_set(s_all)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def test_executor_target_bound_ops(memory_backend) -> None:
    ex = GraphQueryExecutor()
    key = ex.register(memory_backend)
    assert key == memory_backend.target.uri

    scan = ex.scan(memory_backend.target)
    assert scan.kind == "scan"
    assert scan.success
    assert len(scan.rows) == 4
    assert scan.target_uri == memory_backend.target.uri

    lookup = ex.lookup(["n1"], memory_backend.target)
    assert lookup.rows[0]["name"] == "Alice"

    nbr = ex.neighbors("n1", memory_backend.target, direction="outgoing")
    assert len(nbr.rows) == 2

    paths = ex.paths("n1", memory_backend.target, max_depth=2)
    assert paths.kind == "paths"

    ir = build_simple_ir(entity_type="Person", limit=10)
    ir_res = ex.execute_ir(ir, memory_backend.target)
    assert ir_res.kind == "cypher_ir"
    assert ir_res.success

    hybrid = ex.hybrid_search("Alice", memory_backend.target, k=2)
    assert hybrid.kind == "hybrid"
    assert len(hybrid.rows) <= 2


def test_executor_execute_language_dispatch(memory_backend) -> None:
    ex = GraphQueryExecutor(default_backend=memory_backend)
    r = ex.execute(language="scan", params={"entity_type": "Org"})
    assert len(r.rows) == 1
    assert r.rows[0]["id"] == "n2"

    r2 = ex.execute(
        language="lookup",
        params={"entity_ids": ["n3"]},
    )
    assert r2.rows[0]["name"] == "Bob"


def test_executor_refuses_empty_knowledge_graph() -> None:
    class KnowledgeGraph:
        """Stand-in for the extraction KnowledgeGraph type name."""

        def __init__(self) -> None:
            self.entities = {}

    ex = GraphQueryExecutor()
    with pytest.raises(GraphQueryBackendError) as ei:
        ex.register(KnowledgeGraph())  # type: ignore[arg-type]
    assert ei.value.code == "INVALID_REQUEST"
    assert "KnowledgeGraph" in ei.value.message


def test_executor_requires_declared_target(memory_backend) -> None:
    ex = GraphQueryExecutor()
    # Registered under a different key than URI so resolve by URI fails.
    ex.register(memory_backend, key="alt-key")
    with pytest.raises(GraphQueryBackendError) as ei:
        ex.scan(_target(graph_id="other", revision="rev-x"))
    assert ei.value.code == "NOT_FOUND"


def test_executor_no_ambient_default() -> None:
    ex = GraphQueryExecutor()
    with pytest.raises(GraphQueryBackendError) as ei:
        ex.scan()
    assert ei.value.code == "INVALID_TARGET"


# ---------------------------------------------------------------------------
# Explicit federation
# ---------------------------------------------------------------------------


def test_explicit_federation_uses_declared_targets() -> None:
    t_a = _target(graph_id="hr", revision="r-a", storage_profile="hybrid")
    t_b = _target(graph_id="crm", revision="r-b", storage_profile="hybrid")
    a = open_memory_backend(
        t_a,
        nodes=[
            {"id": "n1", "type": "Person", "name": "Alice", "properties": {"dept": "eng"}},
            {"id": "n2", "type": "Person", "name": "Bob"},
        ],
        edges=[
            {
                "id": "e1",
                "type": "MANAGES",
                "source_id": "n1",
                "target_id": "n2",
            }
        ],
    )
    b = open_memory_backend(
        t_b,
        nodes=[
            {"id": "n1", "type": "Person", "name": "Alice", "properties": {"region": "west"}},
            {"id": "c1", "type": "Company", "name": "Acme"},
        ],
        edges=[
            {
                "id": "e2",
                "type": "WORKS_AT",
                "source_id": "n1",
                "target_id": "c1",
            }
        ],
    )

    fed_target = _target(graph_id="federation", revision="fed-1", storage_profile="hybrid")
    fed = open_federated_backend(fed_target, [a, b])
    assert isinstance(fed, FederatedGraphQueryBackend)
    assert len(fed.leaves) == 2
    assert len(fed.leaf_targets) == 2

    # Union of entities (first-wins on id collision)
    nodes = fed.scan(limit=100).rows
    ids = {n["id"] for n in nodes}
    assert ids == {"n1", "n2", "c1"}

    # Cross-graph lookup with provenance
    hits = fed.federate_lookup(["n1"])
    assert len(hits.rows) == 2  # both graphs have n1
    uris = {r["source_target"] for r in hits.rows}
    assert t_a.uri in uris
    assert t_b.uri in uris

    ex = GraphQueryExecutor()
    ex.register(a)
    ex.register(b)
    result = ex.federate([t_a, t_b], operation="lookup", entity_ids=["n1"])
    assert result.kind == "federated_lookup"
    assert result.statistics["declared_targets"] == 2
    assert len(result.rows) == 2


def test_federation_rejects_empty_target_list(memory_backend) -> None:
    ex = GraphQueryExecutor(default_backend=memory_backend)
    with pytest.raises(GraphQueryBackendError) as ei:
        ex.federate([])
    assert ei.value.code == "INVALID_REQUEST"


def test_federation_rejects_knowledge_graph_leaf(memory_backend) -> None:
    class KnowledgeGraph:
        pass

    with pytest.raises(GraphQueryBackendError) as ei:
        FederatedGraphQueryBackend(
            memory_backend.target,
            [memory_backend, KnowledgeGraph()],  # type: ignore[list-item]
        )
    assert ei.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Legacy GraphBackend adapter
# ---------------------------------------------------------------------------


def test_legacy_adapter_neighbors_page(memory_backend) -> None:
    adapter = LegacyGraphBackendAdapter(memory_backend)
    assert adapter.seed_exists("n1")
    assert not adapter.seed_exists("missing")
    page = adapter.scan_type("Person", limit=10)
    assert set(page.entity_ids) == {"n1", "n3", "n4"}
    nbr = adapter.neighbors("n1", direction="outgoing")
    assert len(nbr.edges) == 2
    headers = adapter.get_entity_headers(["n1"])
    assert headers["n1"].name == "Alice"


def test_typed_error_rejects_unknown_code() -> None:
    with pytest.raises(ValueError):
        GraphQueryBackendError("NOT_A_CODE", "nope")


def test_executor_result_json_envelope(memory_backend) -> None:
    ex = GraphQueryExecutor(default_backend=memory_backend)
    result = ex.scan()
    payload = result.to_json_dict()
    assert payload["success"] is True
    assert payload["backend_api_version"] == BACKEND_API_VERSION
    assert payload["row_count"] == 4
    assert "statistics" in payload
