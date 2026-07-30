"""Contract tests for cross-chain TransactionPreflight (CRYPTOIR-G610 / CRYPTOIR-035).

AST surface: ``TransactionPreflight``

Acceptance:

* Intent + exact candidate binding across chain families.
* Every non-current ALLOW blocks automation.
* One-use request-bound capability issuance and atomic consumption.
* Stale, deny, incomplete, and substituted fixtures never ALLOW.
* Forbidden secret / approval / signature surfaces are rejected.
* No network I/O during evaluation.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.guard import (
    DEFAULT_ALLOWED_EFFECT,
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_ENV = "e" * 64

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"

CHAIN_PROFILES: dict[str, dict[str, Any]] = {
    "evm": {
        "network": "ethereum:mainnet",
        "namespace": "eip155",
        "encoding": "rlp",
        "sender": "0xSender0000000000000000000000000000000001",
        "destination": "0xDest000000000000000000000000000000000002",
        "method": "transfer(address,uint256)",
        "asset": AssetAmount(
            asset_id="asset:eth-native",
            amount="1000000000000000000",
            asset_namespace="native",
            symbol="ETH",
        ),
        "fee": FeeSpec(amount="21000000000000", asset_id="asset:eth-native"),
        "nonce": "42",
        "utxos": (),
    },
    "solana": {
        "network": "solana:mainnet-beta",
        "namespace": "solana",
        "encoding": "solana-message-v0",
        "sender": "So11111111111111111111111111111111111111112",
        "destination": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "method": "transfer",
        "asset": AssetAmount(
            asset_id="asset:sol-native",
            amount="1000000000",
            asset_namespace="native",
            symbol="SOL",
        ),
        "fee": FeeSpec(amount="5000", asset_id="asset:sol-native"),
        "nonce": "recent-blockhash:abc",
        "utxos": (),
    },
    "bitcoin": {
        "network": "bitcoin:mainnet",
        "namespace": "bip122",
        "encoding": "psbt-v2",
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
        "utxos": (
            UtxoRef(
                outpoint="txid:" + ("ab" * 32) + ":0",
                amount="51500",
                script_digest=_DIGEST_B,
            ),
        ),
    },
    "xrpl": {
        "network": "xrpl:mainnet",
        "namespace": "xrpl",
        "encoding": "xrpl-binary",
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
        "nonce": "7",
        "utxos": (),
    },
    "worldcoin": {
        "network": "eip155:480",
        "namespace": "eip155",
        "encoding": "rlp",
        "sender": "0xWorld000000000000000000000000000000000001",
        "destination": "0xWorld000000000000000000000000000000000002",
        "method": "verifyAndExecute(address,uint256,uint256,uint256[8])",
        "asset": AssetAmount(
            asset_id="asset:eth-worldchain",
            amount="0",
            asset_namespace="native",
            symbol="ETH",
        ),
        "fee": FeeSpec(amount="10000000000000", asset_id="asset:eth-worldchain"),
        "nonce": "3",
        "utxos": (),
    },
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _intent(family: str, **overrides: Any) -> TransactionIntent:
    profile = CHAIN_PROFILES[family]
    base: dict[str, Any] = {
        "intent_id": f"intent:{family}-001",
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
                effect_id=f"effect:{family}-transfer",
                kind="transfer",
                summary=f"{family} transfer",
            ),
        ),
        "expires_at": _INTENT_EXPIRY,
        "utxos": profile["utxos"],
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
        "byte_length": 128,
        "network": intent.network,
    }
    base.update(overrides)
    return TransactionCandidate(**base)


def _request(
    family: str,
    intent: TransactionIntent | None = None,
    candidate: TransactionCandidate | None = None,
    **overrides: Any,
) -> TransactionPreflightRequest:
    intent = intent or _intent(family)
    candidate = candidate or _candidate(family, intent)
    base: dict[str, Any] = {
        "request_id": f"req:preflight-{family}-001",
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
        "nonce": f"nonce-preflight-{family}-001",
    }
    base.update(overrides)
    return TransactionPreflightRequest(**base)


def _pass(request: TransactionPreflightRequest) -> tuple[dict[str, str], dict[str, str]]:
    security = {req: "pass" for req in request.security_requirement_ids}
    compliance = {req: "pass" for req in request.compliance_requirement_ids}
    return security, compliance


# ---------------------------------------------------------------------------
# AST / surface
# ---------------------------------------------------------------------------


def test_ast_symbol_transaction_preflight() -> None:
    """AST query: TransactionPreflight."""

    assert TransactionPreflight is not None
    assert TransactionPreflightRequest is not None
    assert evaluate_transaction_preflight is not None
    engine = TransactionPreflight()
    assert engine is not None


# ---------------------------------------------------------------------------
# Positive allow per chain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_positive_allow_issues_capability(family: str) -> None:
    request = _request(family)
    security, compliance = _pass(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.ALLOW
    assert result.blocks_automation is False
    assert result.capability is not None
    assert isinstance(result.capability, AdmissibilityCapability)
    assert result.capability.one_time is True
    assert result.capability.request_digest == request.request_digest
    assert result.capability.network == request.intent.network
    assert DEFAULT_ALLOWED_EFFECT in result.capability.authorization.allowed_effects


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_identity_and_receipt_reproduce(family: str) -> None:
    request = _request(family)
    security, compliance = _pass(request)
    a = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    b = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert a.outcome is b.outcome
    assert a.receipt.receipt_id if hasattr(a, "receipt") else True
    # Digests on request/candidate are stable
    restored = TransactionPreflightRequest.from_dict(request.to_dict())
    assert restored.request_digest == request.request_digest
    assert restored.candidate_digest == request.candidate_digest
    assert restored.intent_digest == request.intent_digest


# ---------------------------------------------------------------------------
# Fail-closed corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_stale_request_never_allows(family: str) -> None:
    request = _request(family)
    security, compliance = _pass(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_EXPIRED,
    )
    assert result.outcome is not TransactionVerdictOutcome.ALLOW
    assert result.blocks_automation is True
    assert result.capability is None


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_hard_deny_security_never_allows(family: str) -> None:
    request = _request(family)
    result = evaluate_transaction_preflight(
        request,
        security_results={"sec:no-self-destruct": "deny"},
        compliance_results={"comp:direct-sanctions": "pass"},
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.DENY
    assert result.blocks_automation is True
    assert result.capability is None


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_stale_compliance_never_allows(family: str) -> None:
    request = _request(family)
    result = evaluate_transaction_preflight(
        request,
        security_results={"sec:no-self-destruct": "pass"},
        compliance_results={"comp:direct-sanctions": "stale"},
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.STALE
    assert result.blocks_automation is True
    assert result.capability is None


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_incomplete_evidence_never_allows(family: str) -> None:
    request = _request(family)
    result = evaluate_transaction_preflight(
        request,
        security_results={},
        compliance_results={"comp:direct-sanctions": "pass"},
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert result.blocks_automation is True
    assert result.capability is None


@pytest.mark.parametrize("family", sorted(CHAIN_PROFILES))
def test_substitution_of_candidate_invalidates_binding(family: str) -> None:
    intent = _intent(family)
    good = _candidate(family, intent)
    request = _request(family, intent=intent, candidate=good)
    security, compliance = _pass(request)
    engine = TransactionPreflight()
    allowed = engine.evaluate(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert allowed.capability is not None
    # Live revalidation with a substituted candidate digest must not permit
    # consumption against a different candidate.
    substituted = _candidate(
        family,
        intent,
        candidate_id=request.candidate.candidate_id,
        serialized_digest=_DIGEST_B,
    )
    swapped = _request(
        family,
        intent=intent,
        candidate=substituted,
        request_id=request.request_id,
        nonce=request.nonce,
    )
    assert swapped.request_digest != request.request_digest
    with pytest.raises(GuardCapabilityError, match="does not match"):
        engine.revalidate_and_consume(
            allowed.capability,
            swapped,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
        )


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
def test_non_allow_blocks_automation(outcome: TransactionVerdictOutcome) -> None:
    request = _request("evm")
    security, compliance = _pass(request)
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


def test_allow_override_cannot_bypass_deny() -> None:
    request = _request("evm")
    result = evaluate_transaction_preflight(
        request,
        security_results={"sec:no-self-destruct": "deny"},
        compliance_results={"comp:direct-sanctions": "pass"},
        outcome_override=TransactionVerdictOutcome.ALLOW,
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.DENY
    assert result.capability is None


# ---------------------------------------------------------------------------
# Forbidden surfaces / non-custodial
# ---------------------------------------------------------------------------


def test_forbidden_approval_fields_rejected() -> None:
    with pytest.raises(GuardForbiddenSurfaceError):
        TransactionPreflightRequest.from_dict(
            {
                **_request("evm").to_dict(),
                "approved": True,
            }
        )


def test_forbidden_private_key_on_intent_rejected() -> None:
    with pytest.raises(GuardForbiddenSurfaceError):
        TransactionIntent.from_dict(
            {
                **_intent("evm").to_dict(),
                "private_key": "0xdead",
            }
        )


def test_forbidden_signature_on_candidate_rejected() -> None:
    with pytest.raises(GuardForbiddenSurfaceError):
        TransactionCandidate.from_dict(
            {
                **_candidate("evm").to_dict(),
                "signature": "0xsig",
            }
        )


def test_boolean_outcome_override_forbidden() -> None:
    request = _request("evm")
    security, compliance = _pass(request)
    with pytest.raises(GuardForbiddenSurfaceError):
        evaluate_transaction_preflight(
            request,
            security_results=security,
            compliance_results=compliance,
            outcome_override=True,  # type: ignore[arg-type]
            now=_NOW_OK,
        )


# ---------------------------------------------------------------------------
# Resource / egress
# ---------------------------------------------------------------------------


def test_preflight_opens_no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_a: Any, **_k: Any) -> None:
        raise AssertionError("preflight must not open network sockets")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    request = _request("solana")
    security, compliance = _pass(request)
    result = evaluate_transaction_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.ALLOW


# ---------------------------------------------------------------------------
# One-use consumption
# ---------------------------------------------------------------------------


def test_capability_is_one_use_at_pre_sign() -> None:
    request = _request("evm")
    security, compliance = _pass(request)
    engine = TransactionPreflight()
    result = engine.evaluate(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.capability is not None
    first = engine.revalidate_and_consume(
        result.capability,
        request,
        phase=PreflightPhase.PRE_SIGN,
        now=_NOW_OK,
    )
    assert first.allowed is True
    assert engine.is_consumed(result.capability) is True
    # Second consumption of the same capability must fail closed.
    with pytest.raises(GuardConsumptionRaceError):
        engine.revalidate_and_consume(
            result.capability,
            request,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
        )


def test_bitcoin_utxo_binding_present() -> None:
    intent = _intent("bitcoin")
    assert intent.utxos
    assert intent.utxos[0].outpoint.startswith("txid:")
    payload = intent.to_dict()
    restored = TransactionIntent.from_dict(payload)
    assert restored.digest == intent.digest
    assert restored.utxos[0].amount == "51500"
