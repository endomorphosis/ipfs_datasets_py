"""Contract tests for the smart-contract security gate (CRYPTOIR-G610 / CRYPTOIR-035).

AST surface: ``ContractSafetyGate`` / security gate composition.

Acceptance:

* Exact code/proxy/upgrade/state epochs and required obligations are
  receipt-bound across chain families.
* Disproved, unsupported-required, unknown, stale, unavailable, errored,
  mismatched, or unexecuted analyses never produce automated ALLOW.
* Authority lattice is non-elevating (SAT/monitor/simulation ≠ proof).
* Upgrade / substitution of live epochs invalidates prior permission.
* Forbidden secret and approval surfaces are rejected.
* Offline evaluation opens no sockets.
"""

from __future__ import annotations

import socket
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
from ipfs_datasets_py.processors.wallets.guard.errors import GuardForbiddenSurfaceError
from ipfs_datasets_py.processors.wallets.guard.models import (
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    TransactionCandidate,
    TransactionIntent,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_DIGEST_D = "d" * 64
_DIGEST_E = "e" * 64
_DIGEST_F = "f" * 64
_DIGEST_G = "1" * 64

_ISSUED = "2026-07-28T12:00:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"
_EPOCH_EXPIRY = "2026-07-28T12:20:00Z"
_EVIDENCE_EXPIRY = "2026-07-28T12:09:00Z"

CHAIN_PROFILES: dict[str, dict[str, Any]] = {
    "evm": {
        "network": "ethereum:mainnet",
        "namespace": "eip155",
        "encoding": "rlp",
        "subject": "contract:0xRouterEvm",
        "sender": "0xSender0000000000000000000000000000000001",
        "destination": "0xRouter000000000000000000000000000000002",
        "method": "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
        "asset": AssetAmount(
            asset_id="asset:usdc",
            amount="1000000",
            asset_namespace="erc20",
            symbol="USDC",
        ),
        "fee": FeeSpec(amount="21000000000000", asset_id="asset:eth-native"),
        "nonce": "7",
    },
    "solana": {
        "network": "solana:mainnet-beta",
        "namespace": "solana",
        "encoding": "solana-message-v0",
        "subject": "program:TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "sender": "So11111111111111111111111111111111111111112",
        "destination": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "method": "transferChecked",
        "asset": AssetAmount(
            asset_id="asset:spl-usdc",
            amount="1000000",
            asset_namespace="spl-token",
            symbol="USDC",
        ),
        "fee": FeeSpec(amount="5000", asset_id="asset:sol-native"),
        "nonce": "blockhash:xyz",
    },
    "bitcoin": {
        "network": "bitcoin:mainnet",
        "namespace": "bip122",
        "encoding": "psbt-v2",
        "subject": "script:p2wsh:policy-miniscript-v1",
        "sender": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "destination": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        "method": "spend",
        "asset": AssetAmount(
            asset_id="asset:btc-native",
            amount="50000",
            asset_namespace="native",
            symbol="BTC",
        ),
        "fee": FeeSpec(amount="1500", asset_id="asset:btc-native"),
        "nonce": "n/a",
    },
    "xrpl": {
        "network": "xrpl:mainnet",
        "namespace": "xrpl",
        "encoding": "xrpl-binary",
        "subject": "hook:issuer-policy-v1",
        "sender": "rN7n7otQDd6FczFgLdSqtcsAUxDkw6fzRH",
        "destination": "rLNaPoKeeBjZe2qs6x52yVPZpZ8td4dc6w",
        "method": "Payment",
        "asset": AssetAmount(
            asset_id="asset:xrp-native",
            amount="1000000",
            asset_namespace="native",
            symbol="XRP",
        ),
        "fee": FeeSpec(amount="12", asset_id="asset:xrp-native"),
        "nonce": "11",
    },
    "worldcoin": {
        "network": "eip155:480",
        "namespace": "eip155",
        "encoding": "rlp",
        "subject": "contract:world-id-verifier",
        "sender": "0xWorld000000000000000000000000000000000001",
        "destination": "0xWorld0000000000000000000000000000000000vr",
        "method": "verifyProof(uint256,uint256,uint256[8])",
        "asset": AssetAmount(
            asset_id="asset:eth-worldchain",
            amount="0",
            asset_namespace="native",
            symbol="ETH",
        ),
        "fee": FeeSpec(amount="10000000000000", asset_id="asset:eth-worldchain"),
        "nonce": "2",
    },
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _intent(family: str, **overrides: Any) -> TransactionIntent:
    profile = CHAIN_PROFILES[family]
    base: dict[str, Any] = {
        "intent_id": f"intent:{family}-swap-001",
        "network": profile["network"],
        "sender": profile["sender"],
        "destination": profile["destination"],
        "method": profile["method"],
        "assets": (profile["asset"],),
        "fees": (profile["fee"],),
        "nonce_or_sequence": profile["nonce"],
        "signers": (f"signer:{profile['sender']}",),
        "expected_effects": (
            ExpectedEffect(
                effect_id=f"effect:{family}-primary",
                kind="transfer",
                summary=f"{family} primary effect",
            ),
            ExpectedEffect(
                effect_id=f"effect:{family}-secondary",
                kind="approval",
                summary=f"{family} secondary effect",
            ),
        ),
        "expires_at": _INTENT_EXPIRY,
        "chain_namespace": profile["namespace"],
    }
    base.update(overrides)
    return TransactionIntent(**base)


def _candidate(
    family: str,
    intent: TransactionIntent | None = None,
    **overrides: Any,
) -> TransactionCandidate:
    intent = intent or _intent(family)
    profile = CHAIN_PROFILES[family]
    base: dict[str, Any] = {
        "candidate_id": f"candidate:{family}-001",
        "intent_id": intent.intent_id,
        "serialized_digest": _DIGEST_A,
        "encoding": profile["encoding"],
        "byte_length": 256,
        "network": intent.network,
    }
    base.update(overrides)
    return TransactionCandidate(**base)


def _code_epoch(family: str, **overrides: Any) -> CodeEpoch:
    profile = CHAIN_PROFILES[family]
    base: dict[str, Any] = {
        "epoch_id": f"epoch:{family}-code-v1",
        "subject_id": profile["subject"],
        "kind": EpochKind.CODE,
        "value_digest": _DIGEST_B,
        "network": profile["network"],
        "chain_namespace": profile["namespace"],
        "code_digest": _DIGEST_B,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _proxy_epoch(family: str, **overrides: Any) -> CodeEpoch:
    profile = CHAIN_PROFILES[family]
    base: dict[str, Any] = {
        "epoch_id": f"epoch:{family}-proxy-v1",
        "subject_id": profile["subject"],
        "kind": EpochKind.PROXY,
        "value_digest": _DIGEST_C,
        "network": profile["network"],
        "proxy_implementation_digest": _DIGEST_C,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _upgrade_epoch(family: str, **overrides: Any) -> CodeEpoch:
    profile = CHAIN_PROFILES[family]
    base: dict[str, Any] = {
        "epoch_id": f"epoch:{family}-upgrade-v1",
        "subject_id": profile["subject"],
        "kind": EpochKind.UPGRADE,
        "value_digest": _DIGEST_D,
        "network": profile["network"],
        "upgrade_authority_digest": _DIGEST_D,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _state_epoch(family: str, **overrides: Any) -> CodeEpoch:
    profile = CHAIN_PROFILES[family]
    base: dict[str, Any] = {
        "epoch_id": f"epoch:{family}-state-v1",
        "subject_id": profile["subject"],
        "kind": EpochKind.STATE,
        "value_digest": _DIGEST_E,
        "network": profile["network"],
        "state_digest": _DIGEST_E,
        "block_or_slot": "20100000",
        "observed_at": _ISSUED,
        "expires_at": _EPOCH_EXPIRY,
    }
    base.update(overrides)
    return CodeEpoch(**base)


def _obligation_set(family: str, **overrides: Any) -> RequiredObligationSet:
    base: dict[str, Any] = {
        "set_id": f"oblset:{family}-v1",
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


def _passing_request(family: str, **overrides: Any) -> ContractSafetyRequest:
    intent = overrides.pop("intent", None) or _intent(family)
    candidate = overrides.pop("candidate", None) or _candidate(family, intent)
    code = overrides.pop("code", None) or _code_epoch(family)
    proxy = overrides.pop("proxy", None) or _proxy_epoch(family)
    upgrade = overrides.pop("upgrade", None) or _upgrade_epoch(family)
    state = overrides.pop("state", None) or _state_epoch(family)
    obl_set = overrides.pop("required_obligations", None) or _obligation_set(family)
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
        "request_id": f"req:contract-safety-{family}-001",
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
# AST / surface
# ---------------------------------------------------------------------------


def test_ast_symbols_contract_safety_gate() -> None:
    """AST query: ContractSafetyGate ContractSafetyDecision RequiredObligationSet CodeEpoch."""

    assert ContractSafetyGate is not None
    assert ContractSafetyDecision is not None
    assert RequiredObligationSet is not None
    assert CodeEpoch is not None
    assert evaluate_contract_safety is not None


# ---------------------------------------------------------------------------
# Positive allow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_positive_proved_obligations_allow(family: str) -> None:
    decision = evaluate_contract_safety(_passing_request(family), now=_NOW_OK)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is False
    assert decision.permits_automation()
    assert decision.obligation_results["obl:no-reentrancy"] == "proved"


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_decision_receipt_reproduces(family: str) -> None:
    request = _passing_request(family)
    a = evaluate_contract_safety(request, now=_NOW_OK)
    b = evaluate_contract_safety(request, now=_NOW_OK)
    assert a.digest == b.digest
    restored = ContractSafetyDecision.from_dict(a.to_dict())
    assert restored.digest == a.digest
    assert restored.outcome is TransactionVerdictOutcome.ALLOW


# ---------------------------------------------------------------------------
# Fail-closed corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_disproved_required_never_allows(family: str) -> None:
    request = _passing_request(family)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    intent = request.intent
    candidate = request.candidate
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            candidate,
            outcome=AnalysisOutcome.DISPROVED,
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
    decision = evaluate_contract_safety(
        _passing_request(family, evidence=evidence),
        now=_NOW_OK,
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_unsupported_required_never_allows(family: str) -> None:
    request = _passing_request(family)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            request.intent,
            request.candidate,
            outcome=AnalysisOutcome.UNSUPPORTED,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:auth-least-privilege",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:intent-effect-equality",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(family, evidence=evidence),
        now=_NOW_OK,
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_stale_evidence_never_allows(family: str) -> None:
    decision = evaluate_contract_safety(
        _passing_request(family),
        now=_NOW_EXPIRED,
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_unknown_required_never_allows(family: str) -> None:
    request = _passing_request(family)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            request.intent,
            request.candidate,
            outcome=AnalysisOutcome.UNKNOWN,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:auth-least-privilege",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:intent-effect-equality",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(family, evidence=evidence),
        now=_NOW_OK,
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_unexecuted_analysis_never_allows(family: str) -> None:
    request = _passing_request(family)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            request.intent,
            request.candidate,
            executed=False,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:auth-least-privilege",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:intent-effect-equality",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(family, evidence=evidence),
        now=_NOW_OK,
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_incomplete_evidence_missing_obligation_never_allows(family: str) -> None:
    request = _passing_request(family)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    # Only two of three required obligations
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:auth-least-privilege",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.PROOF,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(family, evidence=evidence),
        now=_NOW_OK,
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


# ---------------------------------------------------------------------------
# Authority non-elevation and upgrade invalidation
# ---------------------------------------------------------------------------


def test_sat_does_not_satisfy_proof_required() -> None:
    assert not authority_satisfies(
        AnalysisAuthority.SAT,
        AnalysisAuthority.PROOF,
    )
    assert authority_satisfies(
        AnalysisAuthority.PROOF,
        AnalysisAuthority.PROOF,
    )


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_weaker_authority_never_allows_proof_obligation(family: str) -> None:
    request = _passing_request(family)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.SAT,  # too weak
            outcome=AnalysisOutcome.PROVED,
        ),
        _evidence(
            "obl:auth-least-privilege",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:intent-effect-equality",
            code,
            request.intent,
            request.candidate,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    decision = evaluate_contract_safety(
        _passing_request(family, evidence=evidence),
        now=_NOW_OK,
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_live_upgrade_invalidates_prior_permission(family: str) -> None:
    request = _passing_request(family)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    upgraded = _code_epoch(
        family,
        epoch_id=code.epoch_id,
        value_digest=_DIGEST_G,
        code_digest=_DIGEST_G,
    )
    decision = evaluate_contract_safety(
        request,
        now=_NOW_OK,
        live_code_epochs=(upgraded,),
    )
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True
    assert any("upgrad" in c.lower() or "epoch" in c.lower() for c in decision.reason_codes)


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_candidate_substitution_never_allows(family: str) -> None:
    intent = _intent(family)
    original = _candidate(family, intent)
    substituted = _candidate(
        family,
        intent,
        candidate_id="candidate:sub",
        serialized_digest=_DIGEST_G,
    )
    request = _passing_request(family, intent=intent, candidate=original)
    code = request.epoch_by_id(request.primary_code_epoch_id)
    # Evidence bound to original candidate but request later uses substituted
    evidence = (
        _evidence(
            "obl:no-reentrancy",
            code,
            intent,
            original,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:auth-least-privilege",
            code,
            intent,
            original,
            authority=AnalysisAuthority.PROOF,
        ),
        _evidence(
            "obl:intent-effect-equality",
            code,
            intent,
            original,
            authority=AnalysisAuthority.STATIC,
        ),
    )
    mismatched = _passing_request(
        family,
        intent=intent,
        candidate=substituted,
        evidence=evidence,
        code=code,
    )
    decision = evaluate_contract_safety(mismatched, now=_NOW_OK)
    assert decision.outcome is not TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is True


# ---------------------------------------------------------------------------
# Forbidden surfaces / egress
# ---------------------------------------------------------------------------


def test_forbidden_approval_surface_rejected() -> None:
    request = _passing_request("evm")
    payload = request.to_dict()
    payload["approved"] = True
    with pytest.raises(GuardForbiddenSurfaceError):
        ContractSafetyRequest.from_dict(payload)


def test_security_gate_opens_no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_a: Any, **_k: Any) -> None:
        raise AssertionError("security gate must not open network sockets")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    decision = evaluate_contract_safety(_passing_request("bitcoin"), now=_NOW_OK)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW


def test_epochs_and_obligations_are_receipt_bound() -> None:
    request = _passing_request("evm")
    decision = evaluate_contract_safety(request, now=_NOW_OK)
    assert decision.obligation_set_digest == request.required_obligations.digest
    assert decision.primary_code_epoch_digest == request.epoch_by_id(
        request.primary_code_epoch_id
    ).digest
    for epoch in request.code_epochs:
        assert epoch.epoch_id in decision.code_epoch_digests
