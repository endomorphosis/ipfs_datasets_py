"""Conformance tests for bounded, fail-closed CVEfixes retrieval."""

from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.graph import (
    CVEfixesGraph,
    GraphConfig,
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.retrieval import (
    BoundedHybridRetriever,
    RetrievalAuthority,
    RetrievalConfig,
    RetrievalEntry,
    RetrievalIndex,
    RetrievalIntegrityError,
    RetrievalQuery,
    RetrievalScope,
    RetrievalScopeError,
    RetrievalValidationError,
    build_retrieval_index,
    graph_entries,
    retrieve_cvefixes,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import GraphEdge, GraphNode


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


def _graph(label: str = "fixture") -> CVEfixesGraph:
    source_cid = _cid(f"{label}-source")
    projection_cid = _cid(f"{label}-projection")
    config_cid = GraphConfig().cid

    def node(node_type: GraphNodeType, **payload: object) -> GraphNode:
        return GraphNode(
            source_cids=(source_cid,),
            parent_cids=(projection_cid,),
            config_cid=config_cid,
            node_type=node_type.value,
            payload={
                **payload,
                "grants_execution_authority": False,
                "retrieval_only": True,
            },
        )

    code_unit = node(
        GraphNodeType.CODE_UNIT,
        path="src/reader.py",
        code_unit_cid=_cid(f"{label}-unit"),
    )
    action = node(
        GraphNodeType.ACTION,
        predicate="call:open untrusted path",
        confidence=1.0,
    )
    effect = node(
        GraphNodeType.EFFECT,
        predicate="path traversal arbitrary file read",
        confidence=0.9,
    )
    nodes = (
        node(GraphNodeType.CWE, cwe_id="CWE-22"),
        node(GraphNodeType.LANGUAGE, language="python"),
        code_unit,
        action,
        effect,
        node(GraphNodeType.MITIGATION, predicate="guard:path_confined"),
    )

    def observes(target: GraphNode) -> GraphEdge:
        return GraphEdge(
            source_cids=(source_cid,),
            parent_cids=(code_unit.cid, target.cid),
            config_cid=config_cid,
            edge_type=GraphEdgeType.OBSERVES.value,
            source_node_cid=code_unit.cid,
            target_node_cid=target.cid,
            payload={
                "authoritative": False,
                "edge_class": GraphEdgeClass.SEMANTIC.value,
                "grants_execution_authority": False,
                "retrieval_only": True,
            },
        )

    return CVEfixesGraph(
        nodes=nodes,
        edges=(observes(action), observes(effect)),
        source_cids=(source_cid,),
        projection_cids=(projection_cid,),
        config_cid=config_cid,
    )


def _partitions(
    graph: CVEfixesGraph, default: str = "train"
) -> dict[str, str]:
    return {node.cid: default for node in graph.nodes}


def _policy_entry(
    graph: CVEfixesGraph,
    *,
    partition: str = "train",
    authority: RetrievalAuthority = RetrievalAuthority.CANDIDATE,
) -> RetrievalEntry:
    return RetrievalEntry(
        node_cid=_cid(f"policy-{partition}-{authority.value}"),
        partition=partition,
        shard_key=f"{partition}:policy",
        kind="policy",
        text="deny unconfined filesystem read",
        source_cids=(graph.source_cids[0],),
        authority=authority,
        effects=("deny",),
        policies=("path-confinement",),
        graph_node=False,
    )


def test_graph_entries_compact_aggregate_provenance_and_long_filters() -> None:
    sources = tuple(_cid(f"aggregate-source-{index}") for index in range(129))
    projection_cid = _cid("aggregate-projection")
    config_cid = GraphConfig().cid
    predicate = f"call:{'x' * 600}"
    node = GraphNode(
        source_cids=sources,
        parent_cids=(projection_cid,),
        config_cid=config_cid,
        node_type=GraphNodeType.ACTION.value,
        payload={
            "grants_execution_authority": False,
            "predicate": predicate,
            "retrieval_only": True,
        },
    )
    graph = CVEfixesGraph(
        nodes=(node,),
        edges=(),
        source_cids=sources,
        projection_cids=(projection_cid,),
        config_cid=config_cid,
    )

    entry = graph_entries(
        graph,
        partition_by_node={node.cid: "train"},
    )[0]

    assert entry.source_cids == (graph.graph_root,)
    assert "aggregate_provenance_via_graph_root" in entry.policies
    assert len(entry.code_facts) == 1
    assert len(entry.code_facts[0]) == 512
    assert hashlib.sha256(predicate.encode("utf-8")).hexdigest() in (
        entry.code_facts[0]
    )


class _EmbeddingPort:
    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [
            [1.0, 0.0] if "path traversal" in text else [0.0, 1.0]
            for text in texts
        ]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return [1.0, 0.0]


def test_hybrid_filters_cover_cwe_language_code_fact_action_effect_and_policy() -> None:
    graph = _graph()
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        extra_entries=(_policy_entry(graph),),
    )
    scope = RetrievalScope(
        partition="train",
        authorities=(
            RetrievalAuthority.NON_AUTHORITATIVE,
            RetrievalAuthority.CANDIDATE,
        ),
    )

    cases = (
        ({"cwes": ("CWE-22",)}, "cwe"),
        ({"languages": ("python",)}, "language"),
        ({"code_facts": ("call:open untrusted path",)}, "action"),
        ({"actions": ("call:open untrusted path",)}, "action"),
        ({"effects": ("path traversal arbitrary file read",)}, "effect"),
        ({"policies": ("path-confinement",)}, "policy"),
    )
    for values, expected_kind in cases:
        response = retrieve_cvefixes(
            graph,
            index,
            RetrievalQuery(text="security", **values),
            scope=scope,
        )
        assert [item.kind for item in response.results] == [expected_kind]
        assert response.results[0].matched_fields


def test_lexical_vector_and_graph_scores_fuse_deterministically() -> None:
    graph = _graph()
    port = _EmbeddingPort()
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        embedding_port=port,
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="0123456789abcdef",
        model_config={"normalize": True, "dimensions": 2},
    )
    start = next(node.cid for node in graph.nodes if node.node_type == "code_unit")
    retriever = BoundedHybridRetriever(graph, index, embedding_port=port)

    first = retriever.retrieve(
        RetrievalQuery(text="path traversal", start_node_cids=(start,)),
        scope=RetrievalScope(partition="train"),
    )
    second = retriever.retrieve(
        RetrievalQuery(text="path traversal", start_node_cids=(start,)),
        scope=RetrievalScope(partition="train"),
    )

    assert first.to_dict() == second.to_dict()
    effect = next(item for item in first.results if item.kind == "effect")
    assert effect.lexical_score > 0
    assert effect.vector_score == pytest.approx(1.0)
    assert effect.graph_score == pytest.approx(0.5)
    assert effect.graph_distance == 1
    assert index.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert index.model_revision == "0123456789abcdef"
    assert index.model_config_cid
    assert port.document_calls == 1
    assert port.query_calls == 2


def test_queries_cap_shards_nodes_results_and_graph_neighborhood() -> None:
    graph = _graph()
    config = RetrievalConfig(
        max_shards=2,
        max_nodes=3,
        max_results=1,
        max_hops=1,
    )
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        config=config,
        shard_count=8,
        extra_entries=(_policy_entry(graph),),
    )
    start = next(node.cid for node in graph.nodes if node.node_type == "code_unit")
    response = retrieve_cvefixes(
        graph,
        index,
        RetrievalQuery(
            text="path",
            start_node_cids=(start,),
            max_shards=2,
            max_nodes=3,
            max_results=1,
            max_hops=1,
        ),
        scope=RetrievalScope(partition="train"),
        config=config,
    )

    assert response.shards_scanned <= 2
    assert response.nodes_scanned <= 3
    assert response.graph_nodes_visited <= 3
    assert len(response.results) <= 1
    assert response.truncated_shards or response.truncated_nodes

    with pytest.raises(RetrievalValidationError, match="ceiling"):
        retrieve_cvefixes(
            graph,
            index,
            RetrievalQuery(text="path", max_results=2),
            scope=RetrievalScope(partition="train"),
            config=config,
        )


def test_partition_crossing_and_authority_broadening_fail_closed() -> None:
    graph = _graph()
    partitions = _partitions(graph)
    test_node = next(iter(partitions))
    partitions[test_node] = "test"
    index = build_retrieval_index(
        graph,
        partition_by_node=partitions,
        extra_entries=(_policy_entry(graph),),
    )
    retriever = BoundedHybridRetriever(graph, index)
    narrow_scope = RetrievalScope(partition="train")

    with pytest.raises(RetrievalScopeError, match="partition"):
        retriever.retrieve(
            RetrievalQuery(text="path", partition="test"),
            scope=narrow_scope,
        )
    with pytest.raises(RetrievalScopeError, match="authority"):
        retriever.retrieve(
            RetrievalQuery(
                text="path",
                authorities=(RetrievalAuthority.CANDIDATE,),
            ),
            scope=narrow_scope,
        )

    response = retriever.retrieve(
        RetrievalQuery(text="path"),
        scope=narrow_scope,
    )
    assert response.partition == "train"
    assert all(item.partition == "train" for item in response.results)
    assert all(
        item.authority is RetrievalAuthority.NON_AUTHORITATIVE
        for item in response.results
    )


def test_shards_are_single_partition_and_partition_map_must_be_total() -> None:
    graph = _graph()
    incomplete = _partitions(graph)
    incomplete.pop(next(iter(incomplete)))
    with pytest.raises(RetrievalScopeError, match="every and only"):
        build_retrieval_index(graph, partition_by_node=incomplete)

    index = build_retrieval_index(
        graph, partition_by_node=_partitions(graph)
    )
    assert all(
        {entry.partition for entry in shard.entries} == {shard.partition}
        for shard in index.shards
    )


def test_index_binds_graph_config_model_config_and_detects_tampering() -> None:
    graph = _graph()
    index = build_retrieval_index(
        graph, partition_by_node=_partitions(graph)
    )
    assert index.graph_root == graph.graph_root
    assert index.graph_config_cid == graph.config_cid
    assert index.retrieval_config_cid == RetrievalConfig().cid
    assert index.index_root == RetrievalIndex.from_json(index.to_json()).index_root

    tampered = deepcopy(index.to_dict())
    tampered["shards"][0]["entries"][0]["text"] += " injected grant"
    with pytest.raises(RetrievalIntegrityError, match="entry_id"):
        RetrievalIndex.from_dict(tampered)

    root_tampered = deepcopy(index.to_dict())
    root_tampered["graph_root"] = _cid("other-graph")
    with pytest.raises(RetrievalIntegrityError, match="index_root"):
        RetrievalIndex.from_dict(root_tampered)

    other = _graph("other")
    with pytest.raises(RetrievalIntegrityError, match="graph root"):
        BoundedHybridRetriever(other, index)


def test_retrieval_never_returns_a_grant_even_for_allow_policy_candidate() -> None:
    graph = _graph()
    candidate = RetrievalEntry(
        node_cid=_cid("allow-candidate"),
        partition="train",
        shard_key="train:policy",
        kind="policy",
        text="allow candidate for offline review",
        source_cids=(graph.source_cids[0],),
        authority=RetrievalAuthority.CANDIDATE,
        effects=("allow",),
        policies=("reviewed-example",),
        graph_node=False,
    )
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        extra_entries=(candidate,),
    )
    response = retrieve_cvefixes(
        graph,
        index,
        RetrievalQuery(text="allow", effects=("allow",)),
        scope=RetrievalScope(
            partition="train",
            authorities=(RetrievalAuthority.CANDIDATE,),
        ),
    )

    assert len(response.results) == 1
    assert response.results[0].authority is RetrievalAuthority.CANDIDATE
    assert response.authorizes_execution is False
    assert response.grants_execution_authority is False
    assert response.results[0].authorizes_execution is False
    assert response.results[0].grants_execution_authority is False
    wire = response.to_dict()
    assert wire["authorizes_execution"] is False
    assert wire["grants_execution_authority"] is False
    assert wire["results"][0]["authorizes_execution"] is False
    assert wire["results"][0]["grants_execution_authority"] is False

    with pytest.raises(RetrievalValidationError, match="never grant"):
        RetrievalEntry(
            node_cid=_cid("bad-grant"),
            partition="train",
            shard_key="train:bad",
            kind="policy",
            text="bad",
            source_cids=(graph.source_cids[0],),
            grants_execution_authority=True,
        )


class _BrokenEmbeddingPort:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("accelerator unavailable")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("accelerator unavailable")


def test_embedding_accelerator_errors_and_dimension_mismatch_fail_closed() -> None:
    graph = _graph()
    with pytest.raises(RetrievalValidationError, match="failed closed"):
        build_retrieval_index(
            graph,
            partition_by_node=_partitions(graph),
            embedding_port=_BrokenEmbeddingPort(),
            model_id="model",
            model_revision="revision",
        )

    port = _EmbeddingPort()
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        embedding_port=port,
        model_id="model",
        model_revision="revision",
    )
    with pytest.raises(RetrievalValidationError, match="dimensions differ"):
        retrieve_cvefixes(
            graph,
            index,
            RetrievalQuery(text="path", embedding=(1.0, 0.0, 0.0)),
            scope=RetrievalScope(partition="train"),
            embedding_port=port,
        )


def test_serialization_rejects_duplicate_fields_and_non_finite_vectors() -> None:
    graph = _graph()
    index = build_retrieval_index(
        graph, partition_by_node=_partitions(graph)
    )
    duplicate = index.to_json().replace(
        '"schema_version":',
        '"schema_version":"duplicate","schema_version":',
        1,
    )
    with pytest.raises(RetrievalIntegrityError, match="duplicate"):
        RetrievalIndex.from_json(duplicate)

    with pytest.raises(RetrievalValidationError, match="finite"):
        RetrievalQuery(text="path", embedding=(float("nan"),))
