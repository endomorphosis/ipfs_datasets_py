"""CRYPTOIR-G770 unit tests for Solidity formalization records."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.ir_core.claims import ProofObligation
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.adapter import (
    AdapterDisposition,
    CandidateAuthority,
    RetrievedPremise,
    adapt_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.formalize import (
    FormalizationStatus,
    SOLIDITY_LOGIC_FAMILY_CANDIDATE,
    SolidityFormalizationRecord,
    SolidityFormalizeError,
    SolidityFormalizer,
    formalize_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.graph import (
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
pragma solidity ^0.8.19;
contract Token {
    mapping(address => uint256) public balances;
    function transfer(address to, uint256 amount) external {
        balances[msg.sender] -= amount;
        balances[to] += amount;
    }
    function mint(address to, uint256 amount) external {
        balances[to] += amount;
    }
}
"""


def _graph():
    raw = {
        "text": SOURCE,
        "source": "etherscan",
        "address": "0x" + "b" * 40,
        "name": "Token",
        "compiler": "v0.8.19",
        "license": "MIT",
        "path": "contracts/Token.sol",
        "n_chars": len(SOURCE),
    }
    adapted = adapt_solidity_cpt_row(raw, row_index=11)
    projection = SolidityGraphProjector().project_adapted(
        adapted, quality_score=0.55
    )
    return build_solidity_security_graph((projection,))


def test_formalize_emits_obligations_that_are_properties_not_proofs() -> None:
    graph = _graph()
    record = formalize_solidity_security_graph(
        graph, partition_cid=graph.config_cid, quality_score=0.55
    )

    assert record.status in {
        FormalizationStatus.FORMALIZED,
        FormalizationStatus.PARTIAL,
    }
    assert record.graph_cid == graph.cid
    assert record.source_cids == graph.source_cids
    assert record.config_cid == graph.config_cid
    assert record.partition_cid == graph.config_cid
    assert record.logic_family == SOLIDITY_LOGIC_FAMILY_CANDIDATE
    assert record.candidate_authority is CandidateAuthority.CANDIDATE
    assert record.quality_is_safety_label is False
    assert record.semantic_prerequisites
    assert record.formulas
    assert record.obligations
    assert all(isinstance(item, ProofObligation) for item in record.obligations)

    for obligation in record.obligations:
        meta = obligation.metadata.to_dict()
        assert meta["obligation_is_not_proof"] is True
        assert meta["is_proof"] is False
        assert meta["proof_authority"] is False
        assert meta["graph_cid"] == graph.cid
        assert meta["config_cid"] == graph.config_cid
        assert meta["partition_cid"] == graph.config_cid
        assert "semantic_prerequisites" in meta
        # Statement encodes a property to check, not a verified theorem.
        body = json.loads(obligation.statement)
        assert body["obligation_is_not_proof"] is True
        assert body["kind"] == "property_to_check"

    for formula in record.formulas:
        assert formula.graph_cid == graph.cid
        assert formula.config_cid == graph.config_cid
        assert formula.partition_cid == graph.config_cid
        assert formula.source_cids == graph.source_cids
        assert formula.candidate_authority in {
            CandidateAuthority.CANDIDATE.value,
            CandidateAuthority.CONTEXT_ONLY.value,
        }
        assert formula.to_dict()["metadata"].get("proof_authority") is False


def test_retrieved_premises_formalize_as_context_only_assumptions() -> None:
    graph = _graph()
    premise = RetrievedPremise(
        premise_id="premise:graphrag:token-flow",
        statement="Context-only retrieved token flow path.",
        source_refs=(graph.source_cids[0],),
    )
    adapted = adapt_solidity_security_graph(
        graph, retrieved_premises=(premise,)
    )
    record = SolidityFormalizer().formalize(adapted)
    context = [
        item
        for item in record.assumptions
        if item.metadata.to_dict().get("authority") == "context_only"
    ]
    assert context
    assert all(
        item.metadata.to_dict().get("proof_authority") is False
        for item in context
    )
    assert any(item.assumption_id == premise.premise_id for item in context)


def test_abstention_when_adapter_abstains() -> None:
    graph = _graph()
    adapted = adapt_solidity_security_graph(graph, force_abstain=True)
    assert adapted.disposition is AdapterDisposition.ABSTAINED
    record = SolidityFormalizer().formalize(adapted)
    assert record.status is FormalizationStatus.ABSTAINED
    assert record.obligations == ()
    assert record.formulas == ()
    assert record.candidate_authority is CandidateAuthority.ABSTAINED


def test_formalization_record_excludes_solver_and_evaluation_features() -> None:
    graph = _graph()
    record = formalize_solidity_security_graph(graph)
    payload = record.to_dict()
    encoded = json.dumps(payload)
    assert "solver_results" not in encoded
    assert "runtime_traces" not in encoded
    assert "evaluation_label" not in encoded
    assert record.record_id
    # Content addressing is stable.
    again = SolidityFormalizationRecord(
        status=record.status,
        declaration_id=record.declaration_id,
        declaration_digest=record.declaration_digest,
        formulas=record.formulas,
        assumptions=record.assumptions,
        obligations=record.obligations,
        graph_cid=record.graph_cid,
        source_cids=record.source_cids,
        config_cid=record.config_cid,
        partition_cid=record.partition_cid,
        logic_family=record.logic_family,
        candidate_authority=record.candidate_authority,
        semantic_prerequisites=record.semantic_prerequisites,
        unsupported_frontiers=record.unsupported_frontiers,
        source_spans=record.source_spans,
        retrieved_premises=record.retrieved_premises,
        quality_score=record.quality_score,
        quality_is_safety_label=False,
    )
    assert again.record_id == record.record_id


def test_obligation_rejects_proof_authority_claim() -> None:
    graph = _graph()
    record = formalize_solidity_security_graph(graph)
    bad = list(record.obligations)
    original = bad[0]
    with pytest.raises(SolidityFormalizeError, match="proof authority"):
        SolidityFormalizationRecord(
            status=record.status,
            declaration_id=record.declaration_id,
            declaration_digest=record.declaration_digest,
            formulas=record.formulas,
            assumptions=record.assumptions,
            obligations=(
                ProofObligation(
                    obligation_id=original.obligation_id,
                    statement=original.statement,
                    assumption_ids=original.assumption_ids,
                    logic_family=original.logic_family,
                    source_refs=original.source_refs,
                    metadata={
                        **original.metadata.to_dict(),
                        "is_proof": True,
                        "proof_authority": True,
                        "obligation_is_not_proof": True,
                    },
                ),
            ),
            graph_cid=record.graph_cid,
            source_cids=record.source_cids,
            config_cid=record.config_cid,
            partition_cid=record.partition_cid,
            logic_family=record.logic_family,
            candidate_authority=record.candidate_authority,
            semantic_prerequisites=record.semantic_prerequisites,
            unsupported_frontiers=record.unsupported_frontiers,
            source_spans=record.source_spans,
        )


def test_quality_never_promoted_to_safety_in_formalization() -> None:
    graph = _graph()
    record = formalize_solidity_security_graph(graph, quality_score=0.99)
    assert record.quality_is_safety_label is False
    assert record.quality_score == pytest.approx(0.99)
    for formula in record.formulas:
        assert "safety_label" not in formula.to_dict()
