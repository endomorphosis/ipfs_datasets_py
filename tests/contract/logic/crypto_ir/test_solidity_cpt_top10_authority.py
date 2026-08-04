"""End-to-end authority contract for the advisory Solidity CPT bridge.

GraphRAG/model/corpus values may select reviewed obligations.  Only the
existing proof and contract-policy gate can emit a ``ContractSafetyDecision``,
and only for independently executed evidence bound to the exact deployment
epoch and transaction candidate.
"""

from __future__ import annotations

from typing import Any

import pytest
from ipfs_datasets_py.logic.crypto_ir.adapters.solidity_cpt_top10 import (
    ReviewedCandidateBinding,
    SolidityCPTCryptoIRAdapter,
    SolidityCPTCryptoIRAdapterError,
)
from ipfs_datasets_py.logic.crypto_ir.security_rules import (
    FormalTargetKind,
    ObligationCategory,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    AnalysisOutcome,
    TransactionVerdictOutcome,
)
from ipfs_datasets_py.logic.ir_core.claims import ProofObligation as CandidateObligation
from ipfs_datasets_py.logic.ir_core.identity import cid_v1
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.adapter import (
    CandidateAuthority,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.formalize import (
    FormalizationStatus,
    SolidityFormalizationRecord,
)
from ipfs_datasets_py.processors.wallets.guard.contract_gate import (
    AnalysisAuthority,
    CodeEpoch,
    ContractSafetyDecision,
    ContractSafetyRequest,
    EpochKind,
    ObligationAnalysisEvidence,
    RequiredObligationSet,
    evaluate_contract_safety,
)
from ipfs_datasets_py.processors.wallets.guard.errors import GuardValidationError
from ipfs_datasets_py.processors.wallets.guard.models import (
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    TransactionCandidate,
    TransactionIntent,
)

_ISSUED = "2026-07-31T12:00:00Z"
_NOW = "2026-07-31T12:01:00Z"
_EXPIRY = "2026-07-31T12:10:00Z"
_EVIDENCE_EXPIRY = "2026-07-31T12:05:00Z"
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


def _formalization(
    *,
    quality_score: float = 0.99,
) -> SolidityFormalizationRecord:
    source_cid = cid_v1(b"solidity-source")
    graph_cid = cid_v1(b"solidity-graph")
    config_cid = cid_v1(b"solidity-config")
    partition_cid = cid_v1(b"solidity-partition")
    candidate = CandidateObligation(
        obligation_id="candidate:reentrancy:withdraw",
        statement=(
            "For every withdraw call, external interaction must not precede "
            "the bound balance-state update."
        ),
        assumption_ids=("assumption:exact-call-graph",),
        logic_family="solidity_verification_condition",
        source_refs=(source_cid,),
        metadata={
            "candidate_authority": "candidate",
            "config_cid": config_cid,
            "graph_cid": graph_cid,
            "is_proof": False,
            "obligation_is_not_proof": True,
            "partition_cid": partition_cid,
            "proof_authority": False,
            "quality_score": quality_score,
            "retrieval_rank": 1,
            "model_confidence": 0.999,
            "semantic_prerequisites": [
                "inert_solidity_parse",
                "exact_call_graph",
            ],
            "source_cids": [source_cid],
        },
    )
    return SolidityFormalizationRecord(
        status=FormalizationStatus.FORMALIZED,
        declaration_id="declaration:withdraw",
        declaration_digest=_DIGEST_A,
        formulas=(),
        assumptions=(),
        obligations=(candidate,),
        graph_cid=graph_cid,
        source_cids=(source_cid,),
        config_cid=config_cid,
        partition_cid=partition_cid,
        logic_family="solidity_verification_condition",
        candidate_authority=CandidateAuthority.CANDIDATE,
        semantic_prerequisites=(
            "inert_solidity_parse",
            "exact_call_graph",
        ),
        unsupported_frontiers=(),
        source_spans=(),
        quality_score=quality_score,
        quality_is_safety_label=False,
    )


def _bridge():
    formalization = _formalization()
    result = SolidityCPTCryptoIRAdapter().adapt(
        formalization,
        bindings=(
            ReviewedCandidateBinding(
                source_obligation_id="candidate:reentrancy:withdraw",
                review_id="review:solidity:withdraw:17",
                reviewer_id="reviewer:contract-security",
                required_fact_ids=(
                    "fact:withdraw:external-call",
                    "fact:withdraw:balance-write",
                ),
                required_semantic_dimensions=(
                    "inert_solidity_parse",
                    "exact_call_graph",
                    "exact_deployed_code_epoch",
                ),
                category=ObligationCategory.CALLBACK_REENTRANCY,
                formal_target_kind=FormalTargetKind.FOL,
            ),
        ),
    )
    return formalization, result


def _intent() -> TransactionIntent:
    return TransactionIntent(
        intent_id="intent:withdraw:17",
        network="ethereum:mainnet",
        sender="0xSender0000000000000000000000000000000001",
        destination="0xVault0000000000000000000000000000000002",
        method="withdraw(uint256)",
        assets=(
            AssetAmount(
                asset_id="asset:eth",
                amount="1",
                asset_namespace="native",
                symbol="ETH",
            ),
        ),
        fees=(FeeSpec(amount="1", asset_id="asset:eth"),),
        nonce_or_sequence="17",
        signers=("signer:sender",),
        expected_effects=(
            ExpectedEffect(
                effect_id="effect:withdraw",
                kind="transfer",
                summary="withdraw one bound unit",
            ),
        ),
        expires_at=_EXPIRY,
        chain_namespace="eip155",
    )


def _candidate(intent: TransactionIntent) -> TransactionCandidate:
    return TransactionCandidate(
        candidate_id="candidate:transaction:withdraw:17",
        intent_id=intent.intent_id,
        serialized_digest=_DIGEST_A,
        encoding="rlp",
        byte_length=128,
        network=intent.network,
    )


def _epoch(**overrides: Any) -> CodeEpoch:
    value: dict[str, Any] = {
        "epoch_id": "epoch:vault-code:17",
        "subject_id": "contract:vault",
        "kind": EpochKind.CODE,
        "value_digest": _DIGEST_B,
        "network": "ethereum:mainnet",
        "chain_namespace": "eip155",
        "code_digest": _DIGEST_B,
        "block_or_slot": "21000000",
        "observed_at": _ISSUED,
        "expires_at": _EXPIRY,
    }
    value.update(overrides)
    return CodeEpoch(**value)


def _request(
    *,
    evidence: tuple[ObligationAnalysisEvidence, ...] = (),
    epoch: CodeEpoch | None = None,
) -> ContractSafetyRequest:
    _, bridge = _bridge()
    intent = _intent()
    candidate = _candidate(intent)
    code_epoch = epoch or _epoch()
    return ContractSafetyRequest(
        request_id="request:withdraw:17",
        intent=intent,
        candidate=candidate,
        required_obligations=RequiredObligationSet(
            set_id="obligation-set:withdraw:17",
            obligation_ids=(bridge.obligations[0].obligation_id,),
            default_authority=AnalysisAuthority.PROOF,
            policy_id="policy:contract-safety",
            policy_revision="1.0.0",
        ),
        code_epochs=(code_epoch,),
        evidence=evidence,
        tenant_id="tenant:contract-tests",
        actor_id="actor:policy-engine",
        policy_id="policy:contract-safety",
        issued_at=_ISSUED,
        expiry=_EXPIRY,
        primary_code_epoch_id=code_epoch.epoch_id,
    )


def _analysis(
    request: ContractSafetyRequest,
    *,
    authority: AnalysisAuthority = AnalysisAuthority.PROOF,
    outcome: AnalysisOutcome = AnalysisOutcome.PROVED,
    executed: bool = True,
    freshness_expires_at: str = _EVIDENCE_EXPIRY,
) -> ObligationAnalysisEvidence:
    epoch = request.code_epochs[0]
    obligation_id = request.required_obligations.obligation_ids[0]
    return ObligationAnalysisEvidence(
        evidence_id="evidence:withdraw:17",
        obligation_id=obligation_id,
        outcome=outcome,
        authority=authority,
        code_epoch_id=epoch.epoch_id,
        code_epoch_digest=epoch.digest,
        executed=executed,
        receipt_id="proof-receipt:withdraw:17",
        effect_ids=("effect:withdraw",),
        candidate_digest=request.candidate.digest,
        intent_digest=request.intent.digest,
        freshness_expires_at=freshness_expires_at,
    )


def test_bridge_emits_only_reviewed_rules_and_obligations_not_a_verdict() -> None:
    formalization, bridge = _bridge()
    wire = bridge.to_dict()

    assert bridge.formalization_cid == formalization.record_id
    assert len(bridge.rules) == len(bridge.obligations) == 1
    assert bridge.proof_authority is False
    assert bridge.transaction_authority is False
    assert wire["candidate_authority"] == "candidate"
    assert wire["proof_authority"] is False
    assert wire["transaction_authority"] is False
    assert "outcome" not in wire
    assert "safety_verdict" not in wire
    assert "contract_safety_decision" not in wire
    assert not isinstance(bridge, ContractSafetyDecision)
    restored = type(bridge).from_dict(wire)
    assert restored.to_dict() == wire

    rule = bridge.rules[0]
    obligation = bridge.obligations[0]
    assert "quality_score" not in dict(rule.attributes)
    assert obligation.required_fact_ids == (
        "fact:withdraw:external-call",
        "fact:withdraw:balance-write",
    )
    assert set(formalization.semantic_prerequisites) <= set(
        obligation.required_semantic_dimensions
    )
    assert "independent_executed_proof_receipt" in obligation.required_evidence
    assert "exact_deployed_code_epoch" in obligation.required_evidence
    assert dict(obligation.attributes)["proof_authority"] is False


def test_unreviewed_or_semantically_incomplete_candidates_fail_closed() -> None:
    formalization = _formalization()
    adapter = SolidityCPTCryptoIRAdapter()

    with pytest.raises(SolidityCPTCryptoIRAdapterError, match="reviewed"):
        adapter.adapt(formalization, bindings=())
    with pytest.raises(
        SolidityCPTCryptoIRAdapterError, match="semantic prerequisites"
    ):
        adapter.adapt(
            formalization,
            bindings=(
                ReviewedCandidateBinding(
                    source_obligation_id="candidate:reentrancy:withdraw",
                    review_id="review:incomplete",
                    reviewer_id="reviewer:security",
                    required_fact_ids=("fact:withdraw:external-call",),
                    required_semantic_dimensions=("inert_solidity_parse",),
                ),
            ),
        )


def test_corpus_retrieval_model_and_candidate_values_cannot_allow() -> None:
    formalization, bridge = _bridge()
    assert formalization.quality_score == pytest.approx(0.99)
    source_meta = formalization.obligations[0].metadata.to_dict()
    assert source_meta["retrieval_rank"] == 1
    assert source_meta["model_confidence"] == pytest.approx(0.999)
    assert bridge.proof_authority is False

    decision = evaluate_contract_safety(_request(), now=_NOW)
    assert isinstance(decision, ContractSafetyDecision)
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation
    assert not decision.permits_automation()
    assert next(iter(decision.obligation_results.values())) == "unexecuted"


@pytest.mark.parametrize(
    "authority",
    [
        AnalysisAuthority.SAT,
        AnalysisAuthority.SIMULATION,
        AnalysisAuthority.MONITOR,
        AnalysisAuthority.STATIC,
    ],
)
def test_non_proof_authorities_cannot_satisfy_reviewed_proof_obligation(
    authority: AnalysisAuthority,
) -> None:
    request = _request()
    evidence = _analysis(request, authority=authority)
    guarded = _request(evidence=(evidence,))
    decision = evaluate_contract_safety(guarded, now=_NOW)

    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation
    assert next(iter(decision.obligation_results.values())) == "authority_mismatch"


def test_stale_or_unexecuted_candidate_result_cannot_allow() -> None:
    request = _request()
    stale = _analysis(
        request,
        freshness_expires_at="2026-07-31T12:00:30Z",
    )
    stale_decision = evaluate_contract_safety(
        _request(evidence=(stale,)), now=_NOW
    )
    assert stale_decision.outcome is TransactionVerdictOutcome.STALE
    assert stale_decision.blocks_automation

    unexecuted = _analysis(request, executed=False)
    unexecuted_decision = evaluate_contract_safety(
        _request(evidence=(unexecuted,)), now=_NOW
    )
    assert unexecuted_decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert unexecuted_decision.blocks_automation


def test_bridge_payload_cannot_be_injected_as_analysis_evidence() -> None:
    _, bridge = _bridge()
    request = _request()
    wire = request.to_dict()
    wire["evidence"] = [bridge.to_dict()]

    with pytest.raises(GuardValidationError):
        ContractSafetyRequest.from_dict(wire)


def test_only_exact_executed_proof_through_existing_gate_can_allow() -> None:
    request = _request()
    proof = _analysis(request)
    proved_request = _request(evidence=(proof,))
    decision = evaluate_contract_safety(proved_request, now=_NOW)

    assert isinstance(decision, ContractSafetyDecision)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.permits_automation()
    assert decision.primary_code_epoch_digest == proved_request.code_epochs[0].digest
    assert decision.candidate_digest == proved_request.candidate.digest

    changed_epoch = _epoch(value_digest="c" * 64, code_digest="c" * 64)
    mismatched = _request(evidence=(proof,), epoch=changed_epoch)
    rejected = evaluate_contract_safety(mismatched, now=_NOW)
    assert rejected.outcome is not TransactionVerdictOutcome.ALLOW
    assert rejected.blocks_automation
