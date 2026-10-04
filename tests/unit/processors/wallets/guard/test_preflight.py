"""Unit tests for exact transaction intent and fail-closed preflight (CRYPTOIR-G500).

Evidence:

* ``ipfs_datasets_py/processors/wallets/guard/preflight.py``
* request models, capability specialization, guard errors

Acceptance coverage:

* Requests bind network, sender, destination, method/instruction/script, assets,
  amounts, fees, nonce/sequence, UTXOs, signers, serialized bytes, expected
  effects, and expiry.
* Every non-current ``ALLOW`` blocks automation.
* Admissibility capabilities are request-bound, one-use, live-revalidated, and
  atomically consumed.
* No bare boolean, caller-supplied approval, key, signing, or broadcast API.
* Substitution / replay / expiry / concurrent-consumption fail closed.
"""

from __future__ import annotations

import concurrent.futures
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.guard import (
    AdmissibilityCapability,
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    GuardCapabilityError,
    GuardConsumptionRaceError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
    PreflightPhase,
    TransactionCandidate,
    TransactionIntent,
    TransactionPreflight,
    TransactionPreflightRequest,
    UtxoRef,
    evaluate_transaction_preflight,
)
from ipfs_datasets_py.processors.wallets.guard.preflight import (
    DEFAULT_ALLOWED_EFFECT,
    TRANSACTION_PREFLIGHT_INTERFACE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_DIGEST_ENV = "e" * 64

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"
_NOW_INTENT_EXPIRED = "2026-07-28T12:16:00Z"


def _intent(**overrides: Any) -> TransactionIntent:
    base: dict[str, Any] = {
        "intent_id": "intent:transfer-001",
        "network": "ethereum:mainnet",
        "sender": "0xSender0000000000000000000000000000000001",
        "destination": "0xDest000000000000000000000000000000000002",
        "method": "transfer(address,uint256)",
        "assets": (
            AssetAmount(
                asset_id="asset:eth-native",
                amount="1000000000000000000",
                asset_namespace="native",
                symbol="ETH",
            ),
        ),
        "fees": (FeeSpec(amount="21000000000000", asset_id="asset:eth-native"),),
        "nonce_or_sequence": "42",
        "signers": ("signer:0xSender0000000000000000000000000000000001",),
        "expected_effects": (
            ExpectedEffect(
                effect_id="effect:transfer-eth",
                kind="transfer",
                summary="send 1 ETH",
            ),
        ),
        "expires_at": _INTENT_EXPIRY,
        "utxos": (),
        "chain_namespace": "eip155",
    }
    base.update(overrides)
    return TransactionIntent(**base)


def _candidate(
    intent: TransactionIntent | None = None, **overrides: Any
) -> TransactionCandidate:
    intent = intent or _intent()
    base: dict[str, Any] = {
        "candidate_id": "candidate:tx-001",
        "intent_id": intent.intent_id,
        "serialized_digest": _DIGEST_A,
        "encoding": "rlp",
        "byte_length": 128,
        "network": intent.network,
    }
    base.update(overrides)
    return TransactionCandidate(**base)


def _request(
    intent: TransactionIntent | None = None,
    candidate: TransactionCandidate | None = None,
    **overrides: Any,
) -> TransactionPreflightRequest:
    intent = intent or _intent()
    candidate = candidate or _candidate(intent)
    base: dict[str, Any] = {
        "request_id": "req:preflight-001",
        "intent": intent,
        "candidate": candidate,
        "tenant_id": "tenant:alpha",
        "actor_id": "actor:policy-engine",
        "audience_id": "audience:custody-signer",
        "policy_id": "policy:wallet-guard-v1",
        "security_requirement_ids": ("sec:no-self-destruct",),
        "compliance_requirement_ids": ("comp:direct-sanctions",),
        "issued_at": _ISSUED,
        "deadline": _DEADLINE,
        "expiry": _EXPIRY,
        "environment_id": "env:prod",
        "environment_digest": _DIGEST_ENV,
        "nonce": "nonce-preflight-001",
    }
    base.update(overrides)
    return TransactionPreflightRequest(**base)


def _pass_results(request: TransactionPreflightRequest) -> tuple[dict, dict]:
    security = {req: "pass" for req in request.security_requirement_ids}
    compliance = {req: "pass" for req in request.compliance_requirement_ids}
    return security, compliance


# ---------------------------------------------------------------------------
# Model binding
# ---------------------------------------------------------------------------


def test_intent_binds_required_fields() -> None:
    intent = _intent(
        utxos=(
            UtxoRef(
                outpoint="txid:abc:0",
                amount="50000",
                script_digest=_DIGEST_B,
            ),
        )
    )
    payload = intent.to_dict()
    assert payload["network"] == "ethereum:mainnet"
    assert payload["sender"].startswith("0xSender")
    assert payload["destination"].startswith("0xDest")
    assert "transfer" in payload["method"]
    assert payload["assets"][0]["amount"] == "1000000000000000000"
    assert payload["fees"][0]["amount"] == "21000000000000"
    assert payload["nonce_or_sequence"] == "42"
    assert payload["signers"]
    assert payload["expected_effects"]
    assert payload["expires_at"] == _INTENT_EXPIRY
    assert payload["utxos"][0]["outpoint"] == "txid:abc:0"
    restored = TransactionIntent.from_dict(payload)
    assert restored.digest == intent.digest


def test_candidate_binds_serialized_digest() -> None:
    candidate = _candidate()
    assert candidate.serialized_digest == _DIGEST_A
    assert candidate.byte_length == 128
    assert candidate.encoding == "rlp"
    restored = TransactionCandidate.from_dict(candidate.to_dict())
    assert restored.digest == candidate.digest


def test_request_binds_intent_and_candidate() -> None:
    request = _request()
    assert request.intent_digest
    assert request.candidate_digest
    assert request.request_digest
    assert request.candidate.intent_id == request.intent.intent_id
    restored = TransactionPreflightRequest.from_dict(request.to_dict())
    assert restored.request_digest == request.request_digest


def test_request_rejects_intent_candidate_mismatch() -> None:
    intent = _intent()
    candidate = _candidate(intent, intent_id="intent:other")
    with pytest.raises(GuardValidationError, match="intent_id"):
        _request(intent=intent, candidate=candidate)


def test_forbidden_approval_and_key_fields_rejected() -> None:
    with pytest.raises(GuardForbiddenSurfaceError):
        TransactionPreflightRequest.from_dict(
            {
                **_request().to_dict(),
                "approved": True,
            }
        )
    with pytest.raises(GuardForbiddenSurfaceError):
        TransactionIntent.from_dict(
            {
                **_intent().to_dict(),
                "private_key": "0xdead",
            }
        )
    with pytest.raises(GuardForbiddenSurfaceError):
        TransactionCandidate.from_dict(
            {
                **_candidate().to_dict(),
                "signature": "0xsig",
            }
        )


def test_package_exports_required_ast_symbols() -> None:
    import ipfs_datasets_py.processors.wallets.guard as guard

    assert guard.TransactionPreflightRequest is TransactionPreflightRequest
    assert guard.TransactionIntent is TransactionIntent
    assert guard.TransactionCandidate is TransactionCandidate
    assert guard.AdmissibilityCapability is AdmissibilityCapability
    assert guard.TransactionPreflight is TransactionPreflight


# ---------------------------------------------------------------------------
# Preflight evaluation
# ---------------------------------------------------------------------------


def test_allow_issues_one_use_request_bound_capability() -> None:
    request = _request()
    security, compliance = _pass_results(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.ALLOW
    assert result.blocks_automation is False
    assert result.is_allow is True
    assert result.capability is not None
    cap = result.capability
    assert isinstance(cap, AdmissibilityCapability)
    assert cap.one_time is True
    assert cap.request_digest == request.request_digest
    assert cap.intent_digest == request.intent_digest
    assert cap.candidate_digest == request.candidate_digest
    assert cap.network == request.intent.network
    assert cap.tenant_id == request.tenant_id
    assert cap.authorization.one_time is True
    assert DEFAULT_ALLOWED_EFFECT in cap.authorization.allowed_effects


@pytest.mark.parametrize(
    "outcome",
    [
        TransactionVerdictOutcome.DENY,
        TransactionVerdictOutcome.REVIEW,
        TransactionVerdictOutcome.INCONCLUSIVE,
        TransactionVerdictOutcome.STALE,
        TransactionVerdictOutcome.ERROR,
    ],
)
def test_non_allow_blocks_automation_and_issues_no_capability(
    outcome: TransactionVerdictOutcome,
) -> None:
    request = _request()
    security, compliance = _pass_results(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        outcome_override=outcome,
        now=_NOW_OK,
    )
    assert result.outcome is outcome
    assert result.blocks_automation is True
    assert result.capability is None
    assert result.is_allow is False


def test_missing_requirement_result_is_inconclusive() -> None:
    request = _request()
    result = evaluate_transaction_preflight(
        request,
        security_results={},  # missing sec:no-self-destruct
        compliance_results={"comp:direct-sanctions": "pass"},
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert result.blocks_automation is True
    assert result.capability is None
    assert any("missing" in code for code in result.reason_codes)


def test_security_deny_blocks_allow() -> None:
    request = _request()
    result = evaluate_transaction_preflight(
        request,
        security_results={"sec:no-self-destruct": "deny"},
        compliance_results={"comp:direct-sanctions": "pass"},
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.DENY
    assert result.blocks_automation is True
    assert result.capability is None


def test_stale_compliance_blocks_allow() -> None:
    request = _request()
    result = evaluate_transaction_preflight(
        request,
        security_results={"sec:no-self-destruct": "pass"},
        compliance_results={"comp:direct-sanctions": "stale"},
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.STALE
    assert result.blocks_automation is True


def test_allow_override_cannot_bypass_blocking_requirement() -> None:
    request = _request()
    result = evaluate_transaction_preflight(
        request,
        security_results={"sec:no-self-destruct": "deny"},
        compliance_results={"comp:direct-sanctions": "pass"},
        outcome_override=TransactionVerdictOutcome.ALLOW,
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.DENY
    assert result.capability is None


def test_boolean_override_forbidden() -> None:
    request = _request()
    security, compliance = _pass_results(request)
    with pytest.raises(GuardForbiddenSurfaceError):
        evaluate_transaction_preflight(
            request,
            security_results=security,
            compliance_results=compliance,
            outcome_override=True,  # type: ignore[arg-type]
            now=_NOW_OK,
        )


def test_expired_request_blocks_as_stale() -> None:
    request = _request()
    security, compliance = _pass_results(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_EXPIRED,
    )
    assert result.outcome is TransactionVerdictOutcome.STALE
    assert result.blocks_automation is True
    assert result.capability is None


# ---------------------------------------------------------------------------
# Live revalidation, substitution, replay, concurrent consumption
# ---------------------------------------------------------------------------


def _allow_capability(
    request: TransactionPreflightRequest | None = None,
) -> tuple[TransactionPreflight, TransactionPreflightRequest, AdmissibilityCapability]:
    request = request or _request()
    security, compliance = _pass_results(request)
    engine = TransactionPreflight()
    result = engine.evaluate(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.capability is not None
    return engine, request, result.capability


def test_revalidate_and_consume_succeeds_once() -> None:
    engine, request, capability = _allow_capability()
    consumed = engine.revalidate_and_consume(
        capability,
        request,
        phase=PreflightPhase.PRE_SIGN,
        now=_NOW_OK,
    )
    assert consumed.allowed is True
    assert consumed.capability_id == capability.capability_id
    assert engine.is_consumed(capability) is True


def test_replay_consumption_fails_closed() -> None:
    engine, request, capability = _allow_capability()
    engine.revalidate_and_consume(
        capability, request, phase=PreflightPhase.PRE_SIGN, now=_NOW_OK
    )
    with pytest.raises(GuardConsumptionRaceError):
        engine.revalidate_and_consume(
            capability, request, phase=PreflightPhase.PRE_BROADCAST, now=_NOW_OK
        )


def test_substitution_of_candidate_digest_fails() -> None:
    engine, request, capability = _allow_capability()
    mutated_candidate = _candidate(
        request.intent, serialized_digest=_DIGEST_C, candidate_id="candidate:tx-001"
    )
    # Keep candidate_id same so only digest/content changes — rebuild request.
    mutated = _request(
        intent=request.intent,
        candidate=mutated_candidate,
        request_id=request.request_id,
        nonce=request.nonce,
    )
    # Mutating candidate changes request_digest and candidate_digest.
    with pytest.raises(GuardCapabilityError, match="does not match"):
        engine.revalidate_and_consume(
            capability, mutated, phase=PreflightPhase.PRE_SIGN, now=_NOW_OK
        )


def test_substitution_of_destination_fails() -> None:
    engine, request, capability = _allow_capability()
    mutated_intent = _intent(destination="0xAttacker00000000000000000000000000000099")
    # candidate still references original intent_id but content changed
    mutated_candidate = _candidate(mutated_intent, candidate_id=request.candidate.candidate_id)
    mutated = _request(
        intent=mutated_intent,
        candidate=mutated_candidate,
        request_id=request.request_id,
        nonce=request.nonce,
    )
    with pytest.raises(GuardCapabilityError, match="does not match"):
        engine.revalidate_and_consume(
            capability, mutated, phase=PreflightPhase.PRE_SIGN, now=_NOW_OK
        )


def test_network_substitution_fails() -> None:
    engine, request, capability = _allow_capability()
    mutated_intent = _intent(network="ethereum:sepolia")
    mutated_candidate = _candidate(
        mutated_intent,
        candidate_id=request.candidate.candidate_id,
        serialized_digest=request.candidate.serialized_digest,
    )
    mutated = _request(
        intent=mutated_intent,
        candidate=mutated_candidate,
        request_id=request.request_id,
        nonce=request.nonce,
    )
    with pytest.raises(GuardCapabilityError, match="does not match"):
        engine.revalidate_and_consume(
            capability, mutated, phase=PreflightPhase.PRE_SIGN, now=_NOW_OK
        )


def test_expired_capability_fails_at_consumption() -> None:
    engine, request, capability = _allow_capability()
    with pytest.raises(GuardCapabilityError, match="expired"):
        engine.revalidate_and_consume(
            capability, request, phase=PreflightPhase.PRE_SIGN, now=_NOW_EXPIRED
        )


def test_concurrent_consumption_exactly_one_winner() -> None:
    engine, request, capability = _allow_capability()
    results: list[str] = []

    def _attempt() -> str:
        try:
            engine.revalidate_and_consume(
                capability, request, phase=PreflightPhase.PRE_SIGN, now=_NOW_OK
            )
            return "ok"
        except GuardConsumptionRaceError:
            return "race"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_attempt) for _ in range(8)]
        results = [f.result() for f in futures]

    assert results.count("ok") == 1
    assert results.count("race") == 7
    assert engine.is_consumed(capability) is True


def test_no_sign_or_broadcast_api_on_preflight() -> None:
    engine = TransactionPreflight()
    forbidden = {
        "sign",
        "sign_transaction",
        "broadcast",
        "send_raw_transaction",
        "approve",
        "private_key",
    }
    public = {name for name in dir(engine) if not name.startswith("_")}
    assert public.isdisjoint(forbidden)
    assert TRANSACTION_PREFLIGHT_INTERFACE == "TransactionPreflight@1"
    # Module-level helper exists for evaluation only.
    assert callable(evaluate_transaction_preflight)


def test_preflight_result_round_trip_dict() -> None:
    request = _request()
    security, compliance = _pass_results(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    payload = result.to_dict()
    assert payload["outcome"] == "allow"
    assert payload["blocks_automation"] is False
    assert payload["capability"]["one_time"] is True
    assert payload["capability"]["request_digest"] == request.request_digest


def test_utxo_intent_round_trip() -> None:
    intent = _intent(
        network="bitcoin:mainnet",
        method="script:p2wpkh",
        chain_namespace="bip122",
        utxos=(
            UtxoRef(outpoint="aa:0", amount="100000", script_digest=_DIGEST_B),
            UtxoRef(outpoint="bb:1", amount="50000", script_digest=_DIGEST_C),
        ),
        assets=(
            AssetAmount(asset_id="asset:btc", amount="150000", symbol="BTC"),
        ),
        fees=(FeeSpec(amount="250", asset_id="asset:btc"),),
    )
    request = _request(intent=intent, candidate=_candidate(intent, encoding="psbt"))
    security, compliance = _pass_results(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.is_allow
    assert result.capability is not None
    assert len(request.intent.utxos) == 2
