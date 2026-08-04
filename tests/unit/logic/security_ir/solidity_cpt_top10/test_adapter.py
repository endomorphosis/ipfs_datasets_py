"""CRYPTOIR-G770 unit tests for Solidity Security IR adapter."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.adapter import (
    AdapterDisposition,
    CandidateAuthority,
    RetrievedPremise,
    SolidityAdapterError,
    SoliditySecurityIRAdapter,
    adapt_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.graph import (
    GraphNodeType,
    build_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.projector import (
    SolidityGraphProjector,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.source_snapshot import (
    adapt_solidity_cpt_row,
)


SOURCE = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Vault {
    uint256 public balance;
    function deposit() external payable {
        balance += msg.value;
    }
    function withdraw(uint256 amount) external {
        balance -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
    }
}
"""


def _graph(*, quality: float | None = 0.87):
    raw = {
        "text": SOURCE,
        "source": "etherscan",
        "address": "0x" + "a" * 40,
        "name": "Vault",
        "compiler": "v0.8.24",
        "license": "MIT",
        "path": "contracts/Vault.sol",
        "n_chars": len(SOURCE),
    }
    adapted = adapt_solidity_cpt_row(raw, row_index=7)
    projection = SolidityGraphProjector().project_adapted(
        adapted, quality_score=quality
    )
    return build_solidity_security_graph((projection,))


def test_adapt_produces_declaration_with_cid_and_span_bindings() -> None:
    graph = _graph()
    partition_cid = graph.config_cid  # any valid CID-shaped fence marker
    result = adapt_solidity_security_graph(
        graph, partition_cid=partition_cid, quality_score=0.87
    )

    assert result.disposition is AdapterDisposition.DECLARED
    assert result.declaration is not None
    assert result.graph_cid == graph.cid
    assert result.source_cids == graph.source_cids
    assert result.config_cid == graph.config_cid
    assert result.partition_cid == partition_cid
    assert result.candidate_authority is CandidateAuthority.CANDIDATE
    assert "source_grounded_graph" in result.semantic_prerequisites
    assert result.quality_is_safety_label is False
    assert result.quality_score == pytest.approx(0.87)

    declaration = result.declaration
    declaration.validate()
    payload = declaration.to_dict()
    assert "solver_results" not in payload
    assert "runtime_traces" not in payload
    assert declaration.claims
    assert declaration.sources
    for claim in declaration.claims:
        attrs = dict(claim.attributes)
        assert attrs.get("proof_authority") is False
        assert attrs.get("is_proof") is False
        assert attrs.get("graph_cid") == graph.cid
        assert attrs.get("config_cid") == graph.config_cid
        assert attrs.get("partition_cid") == partition_cid
        assert attrs.get("candidate_authority") == CandidateAuthority.CANDIDATE.value

    # Extension carries binding metadata for formalization.
    extension = declaration.extensions[0]
    ext_payload = dict(extension.payload)
    assert ext_payload["obligation_is_not_proof"] is True
    assert ext_payload["result_artifacts_excluded"] is True
    assert ext_payload["quality_is_safety_label"] is False
    assert ext_payload["graph_cid"] == graph.cid


def test_retrieved_premises_become_context_only_assumptions() -> None:
    graph = _graph()
    premise = RetrievedPremise(
        premise_id="premise:retrieved:call-path",
        statement="Retrieved call-path premise from GraphRAG hit.",
        source_refs=(graph.source_cids[0],),
        graph_node_cids=(graph.nodes[0].cid,),
        source_spans=({"start_offset": 0, "end_offset": 4},),
    )
    result = SoliditySecurityIRAdapter().adapt(
        graph, retrieved_premises=(premise,)
    )
    assert result.disposition is AdapterDisposition.DECLARED
    assert result.declaration is not None
    assumptions = result.declaration.assumptions
    assert any(item.assumption_id == premise.premise_id for item in assumptions)
    for item in assumptions:
        attrs = dict(item.attributes)
        if attrs.get("retrieved"):
            assert attrs["authority"] == "context_only"
            assert attrs["proof_authority"] is False
    for retrieved in result.retrieved_premises:
        assert retrieved.authority == "context_only"
        assert retrieved.proof_authority is False


def test_quality_is_never_safety_label_and_unlabeled_rows_remain_unlabeled() -> None:
    graph = _graph(quality=None)
    result = adapt_solidity_security_graph(graph)
    assert result.quality_is_safety_label is False
    # No quality observation means unlabeled for safety purposes.
    assert result.quality_score is None or result.quality_is_safety_label is False
    if result.declaration is not None:
        text = result.declaration.canonical_json().lower()
        # Explicit non-label marker is required; true safety labels are not.
        assert "quality_is_safety_label\":false" in text.replace(" ", "")
        assert '"is_safe":true' not in text.replace(" ", "")
        assert '"security_label":' not in text
        assert '"vulnerability_label":' not in text


def test_retrieved_premise_rejects_proof_authority() -> None:
    with pytest.raises(SolidityAdapterError, match="proof_authority=False"):
        RetrievedPremise(
            premise_id="premise:bad",
            statement="must not grant proof",
            proof_authority=True,
        )


def test_force_abstain_on_unknown_or_lossy_semantics() -> None:
    graph = _graph()
    result = adapt_solidity_security_graph(
        graph,
        force_abstain=True,
        abstain_reason="parser reported lossy assembly region",
    )
    assert result.disposition is AdapterDisposition.ABSTAINED
    assert result.declaration is None
    assert result.candidate_authority is CandidateAuthority.ABSTAINED
    assert result.abstentions
    assert "lossy" in result.abstentions[0].message or "parser" in result.abstentions[0].message


def test_declaration_rejects_result_feature_leakage_from_premises() -> None:
    with pytest.raises(SolidityAdapterError, match="result or safety"):
        RetrievedPremise(
            premise_id="premise:leaky",
            statement="leaks solver",
            metadata={"solver_results": [{"sat": True}]},
        )


def test_adapter_result_is_content_addressed_and_frozen() -> None:
    graph = _graph()
    first = adapt_solidity_security_graph(graph, partition_cid="")
    second = adapt_solidity_security_graph(graph, partition_cid="")
    assert first.result_id == second.result_id
    assert first.cid == first.result_id
    with pytest.raises(Exception):
        first.graph_cid = "mutated"  # type: ignore[misc]


def test_quality_score_nodes_are_not_converted_to_claims() -> None:
    graph = _graph(quality=0.91)
    result = adapt_solidity_security_graph(graph)
    assert result.declaration is not None
    for claim in result.declaration.claims:
        assert "quality" not in claim.statement.lower() or "not" in claim.statement.lower()
    quality_nodes = graph.nodes_by_type(GraphNodeType.QUALITY_SCORE)
    assert quality_nodes
    for node in quality_nodes:
        payload = dict(node.payload)
        assert payload.get("is_security_label") is False
