"""Unit tests for the smart-contract safety gate (CRYPTOIR-G510 / CRYPTOIR-027).

Evidence:

* ``ipfs_datasets_py/processors/wallets/guard/contract_gate.py``

Acceptance coverage:

* Exact code/proxy/upgrade/state epochs and required obligation set are
  receipt-bound.
* disproved, unsupported-required, unknown, stale, unavailable, errored,
  mismatched, or unexecuted analyses block automated use.
* static, simulation, monitor, SAT, and proof authorities remain distinct.
* An upgraded contract invalidates prior permission.
* Only the transaction whose exact effects and required obligations were
  evaluated may receive a non-blocking decision.
* Deterministic composition and adversarial code/proxy/state/obligation
  substitution tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    AnalysisOutcome,
    TransactionVerdictOutcome,
)
from ipfs_datasets_py.processors.wallets.guard.contract_gate import (
    AnalysisAuthority,
    CodeEpoch,
    ContractSafetyDecision,
    ContractSafetyGate,
    ContractSafetyRequest,
    EpochKind,
    ObligationAnalysisEvidence,
    RequiredObligationSet,
    authority_satisfies,
    evaluate_contract_safety,
)
from ipfs_datasets_py.processors.wallets.guard.errors import (
    GuardForbiddenSurfaceError,
    GuardValidationError,
)
from ipfs_datasets_py.processors.wallets.guard.models import (
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    TransactionCandidate,
    TransactionIntent,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_DIGEST_D = "d" * 64
_DIGEST_E = "e" * 64
_DIGEST_F = "f" * 64

_ISSUED = "2026-07-28T12:00:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"
_EPOCH_EXPIRY = "2026-07-28T12:20:00Z"
_EVIDENCE_EXPIRY = "2026-07-28T12:09:00Z"


def _intent(**overrides: Any) -> TransactionIntent:
    base: dict[str, Any] = {
        "intent_id": "intent:swap-001",
        "network": "ethereum:mainnet",
        "sender": "0xSender0000000000000000000000000000000001",
        "destination": "0xRouter000000000000000000000000000000002",
        "method": "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
        "assets": (
            AssetAmount(
                asset_id="asset:usdc",
                amount="1000000",
                asset_namespace="erc20",
                symbol="USDC",
            ),
        ),
        "fees": (FeeSpec(amount="21000000000000", asset_id="asset:eth-native"),),
        "nonce_or_sequence": "7",
        "signers": ("signer:0xSender0000000000000000000000000000000001",),
        "expected_effects": (
            ExpectedEffect(
                effect_id="effect:swap-usdc-weth",
                kind="swap",
                summary="swap USDC for WETH",
            ),
            ExpectedEffect(
                effect_id="effect:approve-router",
                kind="approval",
                summary="approve router spend",
            ),
        ),
        "expires_at": _INTENT_EXPIRY,
        "chain_namespace": "eip155",
    }
    base.update(overrides)
    return TransactionIntent(**base)


def _candidate(
    intent: TransactionIntent | None = None, **overrides: Any
) -> TransactionCandidate:
    intent = intent or _intent()
    base: dict[str, Any] = {
        "candidate_id": "candidate:tx-swap-001",
        "intent_id": intent.intent_id,
        "serialized_digest": _DIGEST_A,
        "encoding": "rlp",
        "byte_length": 256,
        "network": intent.network,
    }
    base.update(overrides)
    return TransactionCandidate(**base)


def _code_epoch(**overrides: Any) -> CodeEpoch:
    base: dict[str, Any] = {
        "epoch_id": "epoch:router-code-v1",
        "subject_id": "contract:0xRouter",
        "kind": EpochKind.CODE,
        "value_digest": _DIGEST_B,
        "network": "ethereum:mainnet",
        "chain_namespace": "eip155",
        "code_digest": _DIGEST_B,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _proxy_epoch(**overrides: Any) -> CodeEpoch:
    base: dict[str, Any] = {
        "epoch_id": "epoch:router-proxy-v1",
        "subject_id": "contract:0xRouter",
        "kind": EpochKind.PROXY,
        "value_digest": _DIGEST_C,
        "network": "ethereum:mainnet",
        "proxy_implementation_digest": _DIGEST_C,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _upgrade_epoch(**overrides: Any) -> CodeEpoch:
    base: dict[str, Any] = {
        "epoch_id": "epoch:router-upgrade-v1",
        "subject_id": "contract:0xRouter",
        "kind": EpochKind.UPGRADE,
        "value_digest": _DIGEST_D,
        "network": "ethereum:mainnet",
        "upgrade_authority_digest": _DIGEST_D,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _state_epoch(**overrides: Any) -> CodeEpoch:
    base: dict[str, Any] = {
        "epoch_id": "epoch:router-state-v1",
        "subject_id": "contract:0xRouter",
        "kind": EpochKind.STATE,
        "value_digest": _DIGEST_E,
        "network": "ethereum:mainnet",
        "state_digest": _DIGEST_E,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _obligation_set(**overrides: Any) -> RequiredObligationSet:
    base: dict[str, Any] = {
        "set_id": "oblset:router-swap-v1",
        "obligation_ids": (
            "obl:no-reentrancy",
            "obl:auth-least-privilege",
            "obl:intent-effect-equality",
        ),
        "required_authority": {
            "obl:no-reentrancy": AnalysisAuthority.PROOF,
            "obl:auth-least-privilege": AnalysisAuthority.PROOF,
            "obl:intent-effect-equality": AnalysisAuthority.STATIC,
        },
        "default_authority": AnalysisAuthority.PROOF,
        "policy_id": "policy:contract-safety-v1",
        "policy_revision": "1.0.0",
        "assumption_ids": ("asm:trusted-oracle",),
    }
    base.update(overrides)
    return RequiredObligationSet(**base)


def _evidence(
    obligation_id: str,
    epoch: CodeEpoch,
    intent: TransactionIntent,
    candidate: TransactionCandidate,
    **overrides: Any,
) -> ObligationAnalysisEvidence:
    base: dict[str, Any] = {
        "evidence_id": f"ev:{obligation_id}",
        "obligation_id": obligation_id,
        "outcome": AnalysisOutcome.PROVED,
        "authority": AnalysisAuthority.PROOF,
        "code_epoch_id": epoch.epoch_id,
        "code_epoch_digest": epoch.digest,
        "executed": True,
        "receipt_id": f"receipt:{obligation_id}",
        "model_digest": _DIGEST_F,
        "effect_ids": tuple(e.effect_id for e in intent.expected_effects),
        "candidate_digest": candidate.digest,
        "intent_digest": intent.digest,
        "freshness_expires_at": _EVIDENCE_EXPIRY,
        "unavailable": False,
        "summary": f"proved {obligation_id}",
    }
    base.update(overrides)
    return ObligationAnalysisEvidence(**base)


def _passing_request(**overrides: Any) -> ContractSafetyRequest:
    intent = overrides.pop("intent", None) or _intent()
    candidate = overrides.pop("candidate", None) or _candidate(intent)
    code = overrides.pop("code", None) or _code_epoch()
    proxy = overrides.pop("proxy", None) or _proxy_epoch()
    upgrade = overrides.pop("upgrade", None) or _upgrade_epoch()
    state = overrides.pop("state", None) or _state_epoch()
    obl_set = overrides.pop("required_obligations", None) or _obligation_set()
    evidence = overrides.pop("evidence", None)
    if evidence is None:
        evidence = (
            _evidence(
                "obl:no-reentrancy",
                code,
                intent,
                candidate,
                authority=AnalysisAuthority.PROOF,
            ),
            _evidence(
                "obl:auth-least-privilege",
                code,
                intent,
                candidate,
                authority=AnalysisAuthority.PROOF,
            ),
            _evidence(
                "obl:intent-effect-equality",
                code,
                intent,
                candidate,
                authority=AnalysisAuthority.STATIC,
            ),
        )
    base: dict[str, Any] = {
        "request_id": "req:contract-safety-001",
        "intent": intent,
        "candidate": candidate,
        "required_obligations": obl_set,
        "code_epochs": (code, proxy, upgrade, state),
        "evidence": evidence,
        "tenant_id": "tenant:alpha",
        "actor_id": "actor:policy-engine",
        "policy_id": "policy:contract-safety-v1",
        "issued_at": _ISSUED,
        "expiry": _EXPIRY,
        "primary_code_epoch_id": code.epoch_id,
        "proxy_epoch_id": proxy.epoch_id,
        "upgrade_epoch_id": upgrade.epoch_id,
        "state_epoch_id": state.epoch_id,
    }
    base.update(overrides)
    return ContractSafetyRequest(**base)


# ---------------------------------------------------------------------------
# AST surface / model binding
# ---------------------------------------------------------------------------


def test_ast_symbols_exported() -> None:
    """AST query: ContractSafetyGate ContractSafetyDecision RequiredObligationSet CodeEpoch."""

    assert ContractSafetyGate is not None
    assert ContractSafetyDecision is not None
    assert RequiredObligationSet is not None
    assert CodeEpoch is not None
    assert AnalysisAuthority is not None
    assert EpochKind is not None


def test_code_epoch_receipt_bound_and_round_trip() -> None:
    epoch = _code_epoch()
    payload = epoch.to_dict()
    assert payload["kind"] == "code"
    assert payload["value_digest"] == _DIGEST_B
    assert payload["code_digest"] == _DIGEST_B
    restored = CodeEpoch.from_dict(payload)
    assert restored.digest == epoch.digest
    assert restored.epoch_id == epoch.epoch_id


def test_required_obligation_set_receipt_bound() -> None:
    obl = _obligation_set()
    assert obl.required_authority_for("obl:no-reentrancy") is AnalysisAuthority.PROOF
    assert (
        obl.required_authority_for("obl:intent-effect-equality")
        is AnalysisAuthority.STATIC
    )
    restored = RequiredObligationSet.from_dict(obl.to_dict())
    assert restored.digest == obl.digest
    assert restored.obligation_ids == obl.obligation_ids


def test_decision_binds_epochs_and_obligations() -> None:
    request = _passing_request()
    decision = evaluate_contract_safety(request, now=_NOW_OK)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is False
    assert decision.permits_automation()
    assert decision.obligation_set_digest == request.required_obligations.digest
    assert decision.primary_code_epoch_digest == request.epoch_by_id(
        request.primary_code_epoch_id
    ).digest
    assert set(decision.code_epoch_digests) == {
        e.epoch_id for e in request.code_epochs
    }
    assert set(decision.evaluated_effect_ids) == {
        "effect:swap-usdc-weth",
        "effect:approve-router",
    }
    restored = ContractSafetyDecision.from_dict(decision.to_dict())
    assert restored.digest == decision.digest


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_all_proved_under_required_authorities_allows() -> None:
    gate = ContractSafetyGate()
    decision = gate.evaluate(_passing_request(), now=_NOW_OK)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert not decision.blocks_automation
    assert decision.obligation_results["obl:no-reentrancy"] == "proved"
    assert decision.obligation_results["obl:auth-least-privilege"] == "proved"
    assert decision.obligation_results["obl:intent-effect-equality"] == "proved"
    assert decision.authority_results["obl:no-reentrancy"] == "proof"
    assert decision.authority_results["obl:intent-effect-equality"] == "static"


# ---------------------------------------------------------------------------
# Fail-closed outcomes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome,result_key,terminal",
    [
        (AnalysisOutcome.DISPROVED, "disproved", TransactionVerdictOutcome.DENY),
        (
            AnalysisOutcome.UNSUPPORTED,
            "unsupported_required",
            TransactionVerdictOutcome.INCONCLUSIVE,
        ),
        (AnalysisOutcome.UNKNOWN, "unknown", TransactionVerdictOutcome.INCONCLUSIVE),
        (
            AnalysisOutcome.INCONCLUSIVE,
            "unknown",
            TransactionVerdictOutcome.INCONCLUSIVE,
        ),
        (AnalysisOutcome.STALE, "stale", TransactionVerdictOutcome.STALE),
        (AnalysisOutcome.ERROR, "errored", TransactionVerdictOutcome.ERROR),
    ],
)
def test_bad_analysis_outcomes_block(
    outcome: AnalysisOutcome,
    result_key: str,
    terminal: TransactionVerdictOutcome,
) -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            outcome=outcome,
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.outcome is terminal
    assert decision.obligation_results["obl:no-reentrancy"] == result_key
    assert not decision.permits_automation()


def test_unexecuted_blocks() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy", code, intent, candidate, executed=False
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert decision.obligation_results["obl:no-reentrancy"] == "unexecuted"
    assert any(c.startswith("contract.unexecuted:") for c in decision.reason_codes)


def test_missing_evidence_is_unexecuted() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    # Only two of three required obligations supplied.
    evidence = (
        _evidence("obl:no-reentrancy", code, intent, candidate),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.obligation_results["obl:intent-effect-equality"] == "unexecuted"


def test_unavailable_blocks() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy", code, intent, candidate, unavailable=True
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.obligation_results["obl:no-reentrancy"] == "unavailable"


def test_stale_request_blocks() -> None:
    decision = evaluate_contract_safety(_passing_request(), now=_NOW_EXPIRED)
    assert decision.blocks_automation
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert "contract.request_expired" in decision.reason_codes


def test_stale_evidence_freshness_blocks() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            freshness_expires_at="2026-07-28T12:01:00Z",
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert decision.obligation_results["obl:no-reentrancy"] == "stale"


# ---------------------------------------------------------------------------
# Authority non-elevation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provided,required,ok",
    [
        (AnalysisAuthority.PROOF, AnalysisAuthority.PROOF, True),
        (AnalysisAuthority.PROOF, AnalysisAuthority.STATIC, True),
        (AnalysisAuthority.PROOF, AnalysisAuthority.SAT, True),
        (AnalysisAuthority.STATIC, AnalysisAuthority.STATIC, True),
        (AnalysisAuthority.STATIC, AnalysisAuthority.PROOF, False),
        (AnalysisAuthority.SIMULATION, AnalysisAuthority.PROOF, False),
        (AnalysisAuthority.MONITOR, AnalysisAuthority.PROOF, False),
        (AnalysisAuthority.SAT, AnalysisAuthority.PROOF, False),
        (AnalysisAuthority.SAT, AnalysisAuthority.STATIC, False),
        (AnalysisAuthority.MONITOR, AnalysisAuthority.STATIC, False),
        (AnalysisAuthority.SIMULATION, AnalysisAuthority.SIMULATION, True),
        (AnalysisAuthority.MONITOR, AnalysisAuthority.MONITOR, True),
        (AnalysisAuthority.SAT, AnalysisAuthority.SAT, True),
    ],
)
def test_authority_satisfies_non_elevation(
    provided: AnalysisAuthority,
    required: AnalysisAuthority,
    ok: bool,
) -> None:
    assert authority_satisfies(provided, required) is ok


def test_sat_cannot_satisfy_proof_requirement() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.SAT,
            outcome=AnalysisOutcome.PROVED,
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.obligation_results["obl:no-reentrancy"] == "authority_mismatch"
    assert any(
        c.startswith("contract.authority_mismatch:") for c in decision.reason_codes
    )


def test_monitor_and_simulation_remain_distinct_from_proof() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    for auth in (AnalysisAuthority.MONITOR, AnalysisAuthority.SIMULATION):
        evidence = (
            _evidence(
                "obl:no-reentrancy",
                code,
                intent,
                candidate,
                authority=auth,
            ),
            _evidence("obl:auth-least-privilege", code, intent, candidate),
            _evidence(
                "obl:intent-effect-equality",
                code,
                intent,
                candidate,
                authority=AnalysisAuthority.STATIC,
            ),
        )
        decision = evaluate_contract_safety(
            _passing_request(
                intent=intent, candidate=candidate, code=code, evidence=evidence
            ),
            now=_NOW_OK,
        )
        assert decision.blocks_automation
        assert decision.authority_results["obl:no-reentrancy"] == auth.value


# ---------------------------------------------------------------------------
# Adversarial substitution
# ---------------------------------------------------------------------------


def test_code_epoch_digest_substitution_blocks() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            # Adversary swaps in a different epoch digest
            code_epoch_digest=_DIGEST_A,
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert decision.obligation_results["obl:no-reentrancy"] == "mismatched"


def test_proxy_epoch_out_of_scope_blocks() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    proxy = _proxy_epoch()
    # Evidence claims proxy epoch but proxy is not declared in request scope.
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            proxy,
            intent,
            candidate,
            code_epoch_id=proxy.epoch_id,
            code_epoch_digest=proxy.digest,
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    request = _passing_request(
        intent=intent,
        candidate=candidate,
        code=code,
        proxy=proxy,
        evidence=evidence,
        proxy_epoch_id="",  # deliberately not in scope
    )
    decision = evaluate_contract_safety(request, now=_NOW_OK)
    assert decision.blocks_automation
    assert decision.obligation_results["obl:no-reentrancy"] == "mismatched"


def test_candidate_substitution_blocks() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    other = _candidate(intent, candidate_id="candidate:tx-swap-OTHER", serialized_digest=_DIGEST_C)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            candidate_digest=other.digest,
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.obligation_results["obl:no-reentrancy"] == "mismatched"
    assert any(
        c.startswith("contract.candidate_mismatch:") for c in decision.reason_codes
    )


def test_effect_mismatch_blocks_unevaluated_effects() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    # Evidence only covers one of two evaluated effects.
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            effect_ids=("effect:swap-usdc-weth",),
        ),
        _evidence("obl:auth-least-privilege", code, intent, candidate),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.blocks_automation
    assert decision.obligation_results["obl:no-reentrancy"] == "mismatched"
    assert any(
        c.startswith("contract.effect_mismatch:") for c in decision.reason_codes
    )


def test_obligation_set_substitution_invalidates_on_revalidate() -> None:
    request = _passing_request()
    gate = ContractSafetyGate()
    decision = gate.evaluate(request, now=_NOW_OK)
    assert decision.permits_automation()

    swapped = _obligation_set(
        set_id="oblset:router-swap-v2",
        obligation_ids=("obl:no-reentrancy", "obl:auth-least-privilege"),
        required_authority={
            "obl:no-reentrancy": AnalysisAuthority.PROOF,
            "obl:auth-least-privilege": AnalysisAuthority.PROOF,
        },
    )
    # Rebuild a request that differs only in obligation set (and matching evidence).
    intent = request.intent
    candidate = request.candidate
    code = request.epoch_by_id(request.primary_code_epoch_id)
    new_request = _passing_request(
        intent=intent,
        candidate=candidate,
        required_obligations=swapped,
        evidence=(
            _evidence("obl:no-reentrancy", code, intent, candidate),
            _evidence("obl:auth-least-privilege", code, intent, candidate),
        ),
    )
    revalidated = gate.revalidate(decision, new_request, now=_NOW_OK)
    assert revalidated.blocks_automation
    assert revalidated.outcome is TransactionVerdictOutcome.STALE
    assert "contract.revalidation_mismatch" in revalidated.reason_codes


# ---------------------------------------------------------------------------
# Upgrade invalidates prior permission
# ---------------------------------------------------------------------------


def test_upgraded_contract_invalidates_prior_permission() -> None:
    request = _passing_request()
    gate = ContractSafetyGate()
    decision = gate.evaluate(request, now=_NOW_OK)
    assert decision.permits_automation()

    # Live upgrade: same epoch id, new value digest / content.
    upgraded = _code_epoch(
        value_digest=_DIGEST_F,
        code_digest=_DIGEST_F,
    )
    assert upgraded.digest != request.epoch_by_id(request.primary_code_epoch_id).digest

    revalidated = gate.revalidate(
        decision,
        request,
        now=_NOW_OK,
        live_code_epochs=(
            upgraded,
            request.epoch_by_id(request.proxy_epoch_id),
            request.epoch_by_id(request.upgrade_epoch_id),
            request.epoch_by_id(request.state_epoch_id),
        ),
    )
    assert revalidated.blocks_automation
    assert revalidated.outcome is TransactionVerdictOutcome.STALE
    assert any(
        c.startswith("contract.epoch_upgraded:") for c in revalidated.reason_codes
    )


def test_evaluate_with_live_upgraded_epoch_blocks() -> None:
    request = _passing_request()
    upgraded = _code_epoch(value_digest=_DIGEST_F, code_digest=_DIGEST_F)
    decision = evaluate_contract_safety(
        request,
        now=_NOW_OK,
        live_code_epochs=(
            upgraded,
            request.epoch_by_id(request.proxy_epoch_id),
            request.epoch_by_id(request.upgrade_epoch_id),
            request.epoch_by_id(request.state_epoch_id),
        ),
    )
    assert decision.blocks_automation
    assert any(
        c.startswith("contract.epoch_upgraded:") for c in decision.reason_codes
    )


def test_state_epoch_change_invalidates() -> None:
    request = _passing_request()
    gate = ContractSafetyGate()
    decision = gate.evaluate(request, now=_NOW_OK)
    assert decision.permits_automation()

    new_state = _state_epoch(value_digest=_DIGEST_A, state_digest=_DIGEST_A)
    revalidated = gate.revalidate(
        decision,
        request,
        now=_NOW_OK,
        live_code_epochs=(
            request.epoch_by_id(request.primary_code_epoch_id),
            request.epoch_by_id(request.proxy_epoch_id),
            request.epoch_by_id(request.upgrade_epoch_id),
            new_state,
        ),
    )
    assert revalidated.blocks_automation
    assert any("epoch_upgraded" in c for c in revalidated.reason_codes)


# ---------------------------------------------------------------------------
# Exact-effects-only permission
# ---------------------------------------------------------------------------


def test_permit_only_evaluated_effects_and_obligations() -> None:
    request = _passing_request()
    decision = evaluate_contract_safety(request, now=_NOW_OK)
    assert decision.permits_automation()
    # Decision is locked to the exact candidate + effects + obligation set.
    assert decision.candidate_digest == request.candidate_digest
    assert decision.intent_digest == request.intent_digest
    assert decision.obligation_set_id == request.required_obligations.set_id
    assert list(decision.evaluated_effect_ids) == list(request.evaluated_effect_ids)

    # Different candidate cannot reuse the decision via revalidate.
    other_candidate = _candidate(
        request.intent,
        candidate_id="candidate:tx-swap-002",
        serialized_digest=_DIGEST_D,
    )
    other_request = _passing_request(
        intent=request.intent,
        candidate=other_candidate,
    )
    gate = ContractSafetyGate()
    revalidated = gate.revalidate(decision, other_request, now=_NOW_OK)
    assert revalidated.blocks_automation
    assert "contract.revalidation_mismatch" in revalidated.reason_codes


def test_decision_is_deterministic() -> None:
    request = _passing_request()
    a = evaluate_contract_safety(request, now=_NOW_OK)
    b = evaluate_contract_safety(request, now=_NOW_OK)
    assert a.digest == b.digest
    assert a.decision_id == b.decision_id
    assert a.reason_codes == b.reason_codes


# ---------------------------------------------------------------------------
# Forbidden surfaces / validation
# ---------------------------------------------------------------------------


def test_forbidden_approval_fields_rejected() -> None:
    with pytest.raises(GuardForbiddenSurfaceError):
        CodeEpoch.from_dict(
            {
                "epoch_id": "epoch:x",
                "subject_id": "contract:x",
                "kind": "code",
                "value_digest": _DIGEST_A,
                "force_allow": True,
            }
        )


def test_empty_obligation_set_rejected() -> None:
    with pytest.raises(GuardValidationError):
        RequiredObligationSet(set_id="oblset:empty", obligation_ids=())


def test_request_requires_at_least_one_epoch() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    with pytest.raises(GuardValidationError, match="at least one CodeEpoch"):
        ContractSafetyRequest(
            request_id="req:x",
            intent=intent,
            candidate=candidate,
            required_obligations=_obligation_set(),
            code_epochs=(),
            evidence=(),
            tenant_id="tenant:a",
            actor_id="actor:a",
            policy_id="policy:a",
            issued_at=_ISSUED,
            expiry=_EXPIRY,
        )


def test_deny_precedes_inconclusive_when_both_present() -> None:
    intent = _intent()
    candidate = _candidate(intent)
    code = _code_epoch()
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            outcome=AnalysisOutcome.DISPROVED,
        ),
        _evidence(
            "obl:auth-least-privilege",
            code,
            intent,
            candidate,
            outcome=AnalysisOutcome.UNKNOWN,
        ),
        # missing intent-effect evidence → unexecuted
    )
    decision = evaluate_contract_safety(
        _passing_request(
            intent=intent, candidate=candidate, code=code, evidence=evidence
        ),
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert decision.blocks_automation
