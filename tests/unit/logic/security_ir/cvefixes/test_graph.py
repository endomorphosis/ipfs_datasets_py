"""Conformance tests for the typed, integrity-bound CVEfixes graph."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.graph import (
    GRAPH_ONTOLOGY,
    CVEfixesGraph,
    CVEfixesGraphBuilder,
    GraphBuildError,
    GraphConfig,
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
    GraphValidationError,
    SimilarityObservation,
    build_cvefixes_graph,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.projector import (
    EvidencePolarity,
    ExtractionMethod,
    ProjectionResult,
    SemanticFact,
    SemanticKind,
    UnitKind,
    VulnerableFixedPair,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    CodeUnit,
    GraphEdge,
    canonical_config_cid,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


def _projection(label: str = "a") -> ProjectionResult:
    source_cid = _cid(f"source-{label}")
    config_cid = canonical_config_cid({"projector": "fixture"})
    common = {
        "source_cids": (source_cid,),
        "parent_cids": (source_cid,),
        "config_cid": config_cid,
        "unit_kind": "symbol",
        "language": "python",
        "path": "src/reader.py",
    }
    metadata = {
        "commit_hash": "a" * 40,
        "cve_id": "CVE-2024-12345",
        "repository": "https://github.com/example/project",
        "grants_execution_authority": False,
    }
    vulnerable = CodeUnit(
        **common,
        polarity="vulnerable",
        payload={
            **metadata,
            "evidence_polarity": "vulnerable_positive",
        },
    )
    fixed = CodeUnit(
        **common,
        polarity="fixed",
        payload={**metadata, "evidence_polarity": "fixed_negative"},
    )
    pair = VulnerableFixedPair(
        unit_kind=UnitKind.SYMBOL,
        path="src/reader.py",
        unit_index=0,
        symbol="read_user_file",
        vulnerable_cid=vulnerable.cid,
        fixed_cid=fixed.cid,
        source_cid=source_cid,
    )
    facts = (
        SemanticFact(
            kind=SemanticKind.ACTION,
            predicate="call:open",
            evidence_polarity=EvidencePolarity.VULNERABLE_POSITIVE,
            extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
            code_unit_cid=vulnerable.cid,
            source_cid=source_cid,
            config_cid=config_cid,
        ),
        SemanticFact(
            kind=SemanticKind.MITIGATION,
            predicate="added_guard:path_confined",
            evidence_polarity=EvidencePolarity.FIXED_NEGATIVE,
            extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
            code_unit_cid=fixed.cid,
            source_cid=source_cid,
            config_cid=config_cid,
        ),
    )
    return ProjectionResult(
        source_cid=source_cid,
        config_cid=config_cid,
        language="python",
        code_units=(vulnerable, fixed),
        pairs=(pair,),
        semantic_facts=facts,
        diagnostics=(),
    )


def _node_by_subject(graph: CVEfixesGraph, subject_cid: str):
    return next(
        item
        for item in graph.nodes
        if item.payload.get("code_unit_cid") == subject_cid
        or item.payload.get("fact_cid") == subject_cid
    )


def test_builder_materializes_reviewed_ontology_and_adjacency() -> None:
    projection = _projection()
    graph = build_cvefixes_graph(
        (projection,), cwe_by_cve={"CVE-2024-12345": "CWE-22"}
    )

    assert {item.node_type for item in graph.nodes} == {
        item.value
        for item in {
            GraphNodeType.SOURCE,
            GraphNodeType.CVE,
            GraphNodeType.CWE,
            GraphNodeType.REPOSITORY,
            GraphNodeType.COMMIT,
            GraphNodeType.LANGUAGE,
            GraphNodeType.CODE_UNIT,
            GraphNodeType.ACTION,
            GraphNodeType.MITIGATION,
        }
    }
    assert {
        item.edge_type for item in graph.edges
    } >= {
        GraphEdgeType.DESCRIBES.value,
        GraphEdgeType.AFFECTS.value,
        GraphEdgeType.FIXED_BY.value,
        GraphEdgeType.CLASSIFIED_AS.value,
        GraphEdgeType.CONTAINS.value,
        GraphEdgeType.CHANGES.value,
        GraphEdgeType.WRITTEN_IN.value,
        GraphEdgeType.OBSERVES.value,
        GraphEdgeType.PAIRS_WITH.value,
    }
    node_ids = {item.cid for item in graph.nodes}
    edge_ids = {item.cid for item in graph.edges}
    assert set(graph.outgoing) == node_ids
    assert set(graph.incoming) == node_ids
    assert {
        edge_id
        for values in graph.outgoing.values()
        for edge_id in values
    } == edge_ids
    assert {
        edge_id
        for values in graph.incoming.values()
        for edge_id in values
    } == edge_ids


def test_ontology_rejects_wrong_directions_and_edge_classes() -> None:
    GRAPH_ONTOLOGY.validate_edge(
        GraphEdgeType.OBSERVES,
        GraphNodeType.CODE_UNIT,
        GraphNodeType.ACTION,
        edge_class=GraphEdgeClass.SEMANTIC,
    )
    with pytest.raises(GraphValidationError, match="does not permit"):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.OBSERVES,
            GraphNodeType.ACTION,
            GraphNodeType.CODE_UNIT,
            edge_class=GraphEdgeClass.SEMANTIC,
        )
    with pytest.raises(GraphValidationError, match="classified"):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.SIMILAR_TO,
            GraphNodeType.CODE_UNIT,
            GraphNodeType.CODE_UNIT,
            edge_class=GraphEdgeClass.SEMANTIC,
        )


def test_all_edges_bind_sources_existing_endpoints_and_non_authority() -> None:
    projection = _projection()
    graph = CVEfixesGraphBuilder().build((projection,))
    node_ids = {item.cid for item in graph.nodes}

    assert all(item.source_cids for item in graph.edges)
    assert all(item.source_node_cid in node_ids for item in graph.edges)
    assert all(item.target_node_cid in node_ids for item in graph.edges)
    assert all(
        item.payload["grants_execution_authority"] is False
        and item.payload["authoritative"] is False
        for item in graph.edges
    )
    assert all(
        item.payload["grants_execution_authority"] is False
        for item in graph.nodes
    )


def test_edges_bind_shared_evidence_instead_of_endpoint_union() -> None:
    graph = CVEfixesGraphBuilder().build(
        (_projection("a"), _projection("b"))
    )
    nodes = {item.cid: item for item in graph.nodes}

    assert any(len(item.source_cids) > 1 for item in graph.nodes)
    for edge in graph.edges:
        source = nodes[edge.source_node_cid]
        target = nodes[edge.target_node_cid]
        assert set(edge.source_cids) == (
            set(source.source_cids) & set(target.source_cids)
        )


def test_similarity_is_separate_explicitly_non_authoritative_evidence() -> None:
    projection = _projection()
    vulnerable, fixed = projection.code_units
    evidence_cid = _cid("embedding-receipt")
    observation = SimilarityObservation(
        source_record_cid=vulnerable.cid,
        target_record_cid=fixed.cid,
        evidence_cids=(evidence_cid,),
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="0123456789abcdef",
        model_config_cid=_cid("embedding-config"),
        score=0.875,
    )
    graph = CVEfixesGraphBuilder().build(
        (projection,), similarity_observations=(observation,)
    )

    assert len(graph.similarity_edges) == 1
    edge = graph.similarity_edges[0]
    assert edge not in graph.semantic_edges
    assert edge.edge_type == GraphEdgeType.SIMILAR_TO.value
    assert edge.payload["edge_class"] == GraphEdgeClass.SIMILARITY.value
    assert edge.payload["authority"] == "non_authoritative"
    assert edge.payload["authoritative"] is False
    assert edge.payload["grants_execution_authority"] is False
    assert evidence_cid in edge.source_cids
    assert _node_by_subject(graph, vulnerable.cid).cid == edge.source_node_cid


def test_rebuild_is_deterministic_for_input_and_mapping_order() -> None:
    first_projection = _projection("a")
    second_projection = _projection("b")
    first = CVEfixesGraphBuilder().build(
        (first_projection, second_projection),
        cwe_by_cve={"CVE-2024-12345": "CWE-22"},
    )
    second = CVEfixesGraphBuilder().build(
        (second_projection, first_projection),
        cwe_by_cve=dict(
            reversed([("CVE-2024-12345", "CWE-22")])
        ),
    )

    assert first == second
    assert first.graph_root == second.graph_root
    assert first.node_table_root == second.node_table_root
    assert first.edge_table_root == second.edge_table_root
    assert first.adjacency_root == second.adjacency_root
    assert first.canonical_bytes() == second.canonical_bytes()


def test_round_trip_verifies_every_integrity_layer_and_detects_tampering() -> None:
    graph = CVEfixesGraphBuilder().build((_projection(),))
    encoded = graph.to_dict()

    assert CVEfixesGraph.from_dict(encoded) == graph
    assert CVEfixesGraph.from_json(graph.to_json()) == graph
    assert CVEfixesGraph.from_dict(encoded).canonical_bytes() == graph.canonical_bytes()

    tampered_root = deepcopy(encoded)
    tampered_root["graph_root"] = _cid("forged-root")
    with pytest.raises(GraphValidationError, match="graph_root"):
        CVEfixesGraph.from_dict(tampered_root)

    tampered_node = deepcopy(encoded)
    tampered_node["nodes"][0]["payload"]["retrieval_only"] = False
    with pytest.raises(ValueError, match="record_id"):
        CVEfixesGraph.from_dict(tampered_node)

    tampered_adjacency = deepcopy(encoded)
    node_cid = next(
        key
        for key, edge_ids in tampered_adjacency["outgoing"].items()
        if edge_ids
    )
    tampered_adjacency["outgoing"][node_cid] = []
    with pytest.raises(GraphValidationError, match="adjacency"):
        CVEfixesGraph.from_dict(tampered_adjacency)


def test_artifact_rejects_dangling_and_wrongly_directed_edges() -> None:
    graph = CVEfixesGraphBuilder().build((_projection(),))
    edge = graph.edges[0]
    wrong = GraphEdge(
        source_cids=edge.source_cids,
        parent_cids=edge.parent_cids,
        config_cid=edge.config_cid,
        edge_type=GraphEdgeType.OBSERVES.value,
        source_node_cid=edge.source_node_cid,
        target_node_cid=edge.target_node_cid,
        payload={
            **dict(edge.payload),
            "edge_class": GraphEdgeClass.SEMANTIC.value,
        },
    )
    with pytest.raises(GraphValidationError, match="does not permit"):
        CVEfixesGraph(
            nodes=graph.nodes,
            edges=(wrong,),
            source_cids=graph.source_cids,
            projection_cids=graph.projection_cids,
            config_cid=graph.config_cid,
        )

    dangling = GraphEdge(
        source_cids=edge.source_cids,
        parent_cids=edge.parent_cids,
        config_cid=edge.config_cid,
        edge_type=edge.edge_type,
        source_node_cid=edge.source_node_cid,
        target_node_cid=_cid("missing-node"),
        payload=edge.payload,
    )
    with pytest.raises(GraphValidationError, match="dangling"):
        CVEfixesGraph(
            nodes=graph.nodes,
            edges=(dangling,),
            source_cids=graph.source_cids,
            projection_cids=graph.projection_cids,
            config_cid=graph.config_cid,
        )


def test_bounds_duplicates_and_immutability_fail_closed() -> None:
    projection = _projection()
    with pytest.raises(GraphBuildError, match="duplicate projection"):
        CVEfixesGraphBuilder().build((projection, projection))
    with pytest.raises(GraphBuildError, match="max_nodes"):
        CVEfixesGraphBuilder(GraphConfig(max_nodes=1)).build((projection,))

    graph = CVEfixesGraphBuilder().build((projection,))
    with pytest.raises(FrozenInstanceError):
        graph.graph_root = _cid("changed")  # type: ignore[misc]
    with pytest.raises(TypeError):
        graph.outgoing[graph.nodes[0].cid] = ()  # type: ignore[index]
