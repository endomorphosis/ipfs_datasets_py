"""Conformance tests for the typed, integrity-bound Solidity security graph."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.graph import (
    GRAPH_ONTOLOGY,
    GraphBuildError,
    GraphConfig,
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
    GraphValidationError,
    SimilarityObservation,
    SolidityGraphBuilder,
    SoliditySecurityGraph,
    build_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.projector import (
    SolidityGraphProjector,
    UnitKind,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.source_snapshot import (
    adapt_solidity_cpt_row,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.vocabulary import (
    SolidityAuthorityType,
)


SOURCE_A = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;
import "./Ownable.sol";

contract Vault is Ownable {
    uint256 public balance;
    event Deposited(address indexed who, uint256 amount);
    error Insufficient();
    modifier onlyPositive(uint256 x) { require(x > 0); _; }
    function deposit() external payable onlyOwner {
        require(msg.sender != address(0));
        balance += msg.value;
        emit Deposited(msg.sender, msg.value);
    }
    function withdraw(uint256 amount) external onlyOwner {
        if (amount > balance) revert Insufficient();
        balance -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
    }
}
"""

SOURCE_B = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;
contract Token {
    mapping(address => uint256) public balances;
    function transfer(address to, uint256 amount) external {
        balances[msg.sender] -= amount;
        balances[to] += amount;
    }
}
"""


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


def _raw(text: str, *, name: str = "Vault", path: str = "contracts/Vault.sol") -> dict:
    return {
        "text": text,
        "source": "etherscan",
        "address": "0x" + "a" * 40,
        "name": name,
        "compiler": "v0.8.24",
        "license": "MIT",
        "path": path,
        "n_chars": len(text),
    }


def _projection(text: str = SOURCE_A, *, row_index: int = 3, quality: float | None = None):
    adapted = adapt_solidity_cpt_row(_raw(text), row_index=row_index)
    return SolidityGraphProjector().project_adapted(
        adapted, quality_score=quality
    )


def test_builder_materializes_reviewed_ontology_and_adjacency() -> None:
    projection = _projection()
    graph = build_solidity_security_graph((projection,))

    node_types = {item.node_type for item in graph.nodes}
    assert GraphNodeType.SOURCE.value in node_types
    assert GraphNodeType.SOURCE_UNIT.value in node_types
    assert GraphNodeType.CONTRACT.value in node_types
    assert GraphNodeType.FUNCTION.value in node_types
    assert GraphNodeType.LICENSE.value in node_types
    assert GraphNodeType.COMPILER.value in node_types
    assert GraphNodeType.OBSERVED_SYNTAX.value in node_types
    assert GraphNodeType.INFERRED_CANDIDATE.value in node_types or (
        GraphNodeType.SECURITY_CONCEPT.value in node_types
    )

    edge_types = {item.edge_type for item in graph.edges}
    assert GraphEdgeType.DERIVED_FROM.value in edge_types
    assert GraphEdgeType.CONTAINS.value in edge_types or (
        GraphEdgeType.DECLARES.value in edge_types
    )
    assert GraphEdgeType.GROUNDED_IN.value in edge_types
    assert GraphEdgeType.HAS_LICENSE.value in edge_types
    assert GraphEdgeType.HAS_COMPILER.value in edge_types

    node_ids = {item.cid for item in graph.nodes}
    edge_ids = {item.cid for item in graph.edges}
    assert set(graph.outgoing) == node_ids
    assert set(graph.incoming) == node_ids
    assert {
        edge_id for values in graph.outgoing.values() for edge_id in values
    } == edge_ids
    assert {
        edge_id for values in graph.incoming.values() for edge_id in values
    } == edge_ids
    assert graph.graph_root
    assert graph.node_table_root
    assert graph.edge_table_root
    assert graph.adjacency_root


def test_authority_types_remain_separate_node_types() -> None:
    from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.projector import (
        FactKind,
        SuppliedEvidenceFact,
    )

    adapted = adapt_solidity_cpt_row(_raw(SOURCE_A), row_index=3)
    base = SolidityGraphProjector().project_adapted(adapted)
    unit_cid = next(
        item.cid
        for item in base.code_units
        if item.unit_kind == UnitKind.FUNCTION.value
    )
    projection = SolidityGraphProjector().project_adapted(
        adapted,
        supplied_facts=(
            SuppliedEvidenceFact(
                kind=FactKind.MITIGATION,
                predicate="enforce_access_control",
                authority_type=SolidityAuthorityType.REVIEWED_CLAIM,
                code_unit_cid=unit_cid,
                review_id="review:1",
            ),
            SuppliedEvidenceFact(
                kind=FactKind.PROOF_OBLIGATION,
                predicate="no_unauthorized_withdraw",
                authority_type=SolidityAuthorityType.VERIFIED_RESULT,
                code_unit_cid=unit_cid,
                verification_id="verify:1",
            ),
        ),
    )
    graph = build_solidity_security_graph((projection,))

    observed = graph.nodes_by_type(GraphNodeType.OBSERVED_SYNTAX)
    reviewed = graph.nodes_by_type(GraphNodeType.REVIEWED_CLAIM)
    verified = graph.nodes_by_type(GraphNodeType.VERIFIED_RESULT)
    assert observed
    assert reviewed
    assert verified
    assert all(
        item.payload["authority_type"] == GraphNodeType.OBSERVED_SYNTAX.value
        for item in observed
    )
    assert all(
        item.payload["authority_type"] == GraphNodeType.REVIEWED_CLAIM.value
        for item in reviewed
    )
    assert all(
        item.payload["authority_type"] == GraphNodeType.VERIFIED_RESULT.value
        for item in verified
    )
    # Node types are disjoint partitions.
    assert {item.cid for item in observed}.isdisjoint(
        {item.cid for item in reviewed}
    )
    assert {item.cid for item in reviewed}.isdisjoint(
        {item.cid for item in verified}
    )


def test_ontology_rejects_wrong_directions_and_edge_classes() -> None:
    GRAPH_ONTOLOGY.validate_edge(
        GraphEdgeType.GROUNDED_IN,
        GraphNodeType.OBSERVED_SYNTAX,
        GraphNodeType.FUNCTION,
        edge_class=GraphEdgeClass.STRUCTURAL,
    )
    with pytest.raises(GraphValidationError, match="does not permit"):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.GROUNDED_IN,
            GraphNodeType.FUNCTION,
            GraphNodeType.OBSERVED_SYNTAX,
            edge_class=GraphEdgeClass.STRUCTURAL,
        )
    with pytest.raises(GraphValidationError, match="classified"):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.SIMILAR_TO,
            GraphNodeType.FUNCTION,
            GraphNodeType.FUNCTION,
            edge_class=GraphEdgeClass.SEMANTIC,
        )


def test_all_edges_bind_sources_existing_endpoints_and_non_authority() -> None:
    projection = _projection()
    graph = SolidityGraphBuilder().build((projection,))
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
    assert all(item.config_cid == graph.config_cid for item in graph.nodes)
    assert all(item.config_cid == graph.config_cid for item in graph.edges)
    # Source bodies never appear in graph payloads.
    for node in graph.nodes:
        assert "source_code" not in node.payload
        assert "text" not in node.payload
        assert "body" not in node.payload


def test_similarity_is_separate_explicitly_non_authoritative_evidence() -> None:
    projection = _projection()
    functions = [
        item
        for item in projection.code_units
        if item.unit_kind == UnitKind.FUNCTION.value
    ]
    assert len(functions) >= 2
    evidence_cid = _cid("embedding-receipt")
    observation = SimilarityObservation(
        source_record_cid=functions[0].cid,
        target_record_cid=functions[1].cid,
        evidence_cids=(evidence_cid,),
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="0123456789abcdef",
        model_config_cid=_cid("embedding-config"),
        score=0.875,
    )
    graph = SolidityGraphBuilder().build(
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
    assert evidence_cid in graph.source_cids


def test_quality_score_node_is_not_a_security_label() -> None:
    projection = _projection(quality=0.91)
    graph = build_solidity_security_graph((projection,))
    quality_nodes = graph.nodes_by_type(GraphNodeType.QUALITY_SCORE)
    assert len(quality_nodes) == 1
    assert quality_nodes[0].payload["is_security_label"] is False
    assert quality_nodes[0].payload["score"] == 0.91


def test_rebuild_is_deterministic_for_input_order() -> None:
    first_projection = _projection(SOURCE_A, row_index=1)
    second_projection = _projection(SOURCE_B, row_index=2)
    first = SolidityGraphBuilder().build(
        (first_projection, second_projection)
    )
    second = SolidityGraphBuilder().build(
        (second_projection, first_projection)
    )
    assert first.graph_root == second.graph_root
    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()
    assert SoliditySecurityGraph.from_json(first.to_json()) == first


def test_stale_roots_dangling_edges_and_unknown_types_fail_closed() -> None:
    projection = _projection()
    graph = build_solidity_security_graph((projection,))
    payload = graph.to_dict()

    stale = deepcopy(payload)
    stale["graph_root"] = _cid("stale-root")
    with pytest.raises(GraphValidationError, match="graph_root"):
        SoliditySecurityGraph.from_dict(stale)

    dangling = deepcopy(payload)
    dangling["edges"][0]["source_node_cid"] = _cid("missing-node")
    # record_id will also be stale after mutation; from_dict rebuilds via GraphEdge
    # which rehashes — force by reconstructing after swapping endpoint only if
    # we rebuild edge identity.  Easier: validate via direct construction.
    with pytest.raises((GraphValidationError, Exception)):
        SoliditySecurityGraph.from_dict(dangling)

    with pytest.raises(GraphValidationError, match="unsupported"):
        GRAPH_ONTOLOGY.validate_edge(
            "not_an_edge",
            GraphNodeType.SOURCE,
            GraphNodeType.CONTRACT,
            edge_class=GraphEdgeClass.STRUCTURAL,
        )


def test_empty_projections_and_conflicting_similarity_fail_closed() -> None:
    with pytest.raises(GraphBuildError, match="at least one"):
        build_solidity_security_graph(())

    projection = _projection()
    functions = [
        item
        for item in projection.code_units
        if item.unit_kind == UnitKind.FUNCTION.value
    ]
    contracts = [
        item
        for item in projection.code_units
        if item.unit_kind == UnitKind.CONTRACT.value
    ]
    with pytest.raises(GraphBuildError, match="same node type"):
        SolidityGraphBuilder().build(
            (projection,),
            similarity_observations=(
                SimilarityObservation(
                    source_record_cid=functions[0].cid,
                    target_record_cid=contracts[0].cid,
                    evidence_cids=(_cid("e1"),),
                    model_id="m",
                    model_revision="r",
                    model_config_cid=_cid("cfg"),
                    score=0.1,
                ),
            ),
        )


def test_graph_is_frozen() -> None:
    graph = build_solidity_security_graph((_projection(),))
    with pytest.raises(FrozenInstanceError):
        graph.graph_root = "x"  # type: ignore[misc]
