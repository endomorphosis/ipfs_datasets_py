"""Unit tests for the XRPL transaction guard (CRYPTOIR-G550 / CRYPTOIR-029).

Offline adversarial fixtures cover:

* Network, destination/tag, issuer/currency/value, partial-payment/delivered
  amount, sequence/ticket, fee, signer list, ledger epoch, exact candidate.
* Tag/issuer/amount/signature-list mutation, unsupported Hooks, stale ledger,
  and compliance changes block.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.adapters.xrpl import (
    TF_PARTIAL_PAYMENT,
    XRPL_MAINNET_CHAIN_ID,
    XRPL_MAINNET_GENESIS_HASH,
    XRPL_MAINNET_NETWORK,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.guard import (
    GuardCapabilityError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
    PreflightPhase,
)
from ipfs_datasets_py.processors.wallets.xrpl.transaction_guard import (
    XRPL_TRANSACTION_GUARD_INTERFACE,
    LedgerEpoch,
    NormalizedXRPLEffect,
    SignerListBinding,
    XRPLGuardDecision,
    XRPLTransactionBinding,
    XRPLTransactionCandidate,
    XRPLTransactionGuard,
    evaluate_xrpl_transaction_guard,
    normalize_xrpl_tx_effects,
)

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"

ALICE = "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz"
BOB = "rUFiTVw3LSgEqrHV7yPL4nZ1n6f6QgjjfU"
ISSUER = "r3bmF74WayREhyVYaqbu7GqLKvqZvUF3k6"
SIGNER_A = "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz"
SIGNER_B = "rUFiTVw3LSgEqrHV7yPL4nZ1n6f6QgjjfU"

LEDGER_INDEX = 85_000_001
LEDGER_HASH = "AAAA000000000000000000000000000000000000000000000000000000000001"


def _ledger_epoch(**overrides: Any) -> LedgerEpoch:
    base = {
        "ledger_index": LEDGER_INDEX,
        "ledger_hash": LEDGER_HASH,
        "validated": True,
    }
    base.update(overrides)
    return LedgerEpoch(**base)


def _xrp_payment(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent_id": "intent:xrpl-payment-1",
        "account": ALICE,
        "destination": BOB,
        "destination_tag": 42,
        "transaction_type": "Payment",
        "amount": "1000000",
        "fee_drops": "12",
        "flags": 0,
        "sequence": 7,
        "chain_id": XRPL_MAINNET_CHAIN_ID,
        "network": XRPL_MAINNET_NETWORK,
        "genesis_hash": XRPL_MAINNET_GENESIS_HASH,
        "ledger_index": LEDGER_INDEX,
        "ledger_hash": LEDGER_HASH,
        "last_ledger_sequence": LEDGER_INDEX + 100,
    }
    payload.update(overrides)
    return payload


def _issued_payment(**overrides: Any) -> dict[str, Any]:
    payload = _xrp_payment(
        intent_id="intent:xrpl-issued-1",
        amount={"currency": "USD", "issuer": ISSUER, "value": "25.5"},
        destination_tag=99,
    )
    payload.update(overrides)
    return payload


def _partial_payment(**overrides: Any) -> dict[str, Any]:
    payload = _xrp_payment(
        intent_id="intent:xrpl-partial-1",
        flags=TF_PARTIAL_PAYMENT,
        amount="5000000",
        delivered_amount="1000000",
        meta={"delivered_amount": "1000000", "TransactionResult": "tesSUCCESS"},
    )
    payload.update(overrides)
    return payload


def _guard(**kwargs: Any) -> XRPLTransactionGuard:
    return XRPLTransactionGuard(**kwargs)


def _request_for(
    guard: XRPLTransactionGuard,
    binding: XRPLTransactionBinding,
    request_id: str = "req:xrpl-1",
):
    return guard.to_preflight_request(
        binding,
        request_id=request_id,
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )


# ---------------------------------------------------------------------------
# AST / import surface
# ---------------------------------------------------------------------------


def test_ast_symbols_exported() -> None:
    from ipfs_datasets_py.processors.wallets.xrpl import transaction_guard as mod

    assert hasattr(mod, "XRPLTransactionGuard")
    assert hasattr(mod, "XRPLTransactionCandidate")
    assert callable(mod.XRPLTransactionGuard)
    assert callable(mod.XRPLTransactionCandidate)


def test_interface_constants() -> None:
    guard = _guard()
    assert guard.interface == XRPL_TRANSACTION_GUARD_INTERFACE
    assert "xrpl" in guard.schema_version


# ---------------------------------------------------------------------------
# Candidate / effect normalization
# ---------------------------------------------------------------------------


def test_candidate_binds_network_destination_tag_and_amount() -> None:
    cand = XRPLTransactionCandidate.from_dict(_xrp_payment())
    assert cand.chain_id == XRPL_MAINNET_CHAIN_ID
    assert cand.network == XRPL_MAINNET_NETWORK
    assert cand.destination == BOB
    assert cand.destination_tag == 42
    assert cand.sequence == 7
    assert cand.fee_drops == "12"
    assert cand.candidate_digest


def test_normalize_effects_xrp_and_issued() -> None:
    xrp_fx = normalize_xrpl_tx_effects(
        {
            "Account": ALICE,
            "Destination": BOB,
            "DestinationTag": 1,
            "TransactionType": "Payment",
            "Amount": "1000",
            "Fee": "12",
            "Sequence": 1,
            "Flags": 0,
        }
    )
    assert xrp_fx[0].amount_kind == "xrp"
    assert xrp_fx[0].amount_value == "1000"
    assert xrp_fx[0].destination_tag == 1

    issued_fx = normalize_xrpl_tx_effects(
        {
            "Account": ALICE,
            "Destination": BOB,
            "TransactionType": "Payment",
            "Amount": {"currency": "USD", "issuer": ISSUER, "value": "10"},
            "Fee": "12",
            "Sequence": 2,
        }
    )
    assert issued_fx[0].amount_kind == "issued"
    assert issued_fx[0].issuer == ISSUER
    assert issued_fx[0].currency == "USD"


def test_partial_payment_requires_delivered_at_bind_eval() -> None:
    guard = _guard()
    # Without delivered amount, bind succeeds but evaluate blocks.
    cand = _partial_payment()
    del cand["delivered_amount"]
    cand["meta"] = {"TransactionResult": "tesSUCCESS"}
    binding = guard.bind_transaction(cand, ledger_epoch=_ledger_epoch())
    assert binding.effects[0].partial_payment is True
    request = _request_for(guard, binding, "req:partial-no-delivered")
    decision = guard.evaluate(
        binding,
        request=request,
        now=_NOW_OK,
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
    )
    assert decision.blocks_automation is True
    assert decision.allowed is False
    assert any("partial" in c for c in decision.reason_codes)


def test_bind_rejects_forbidden_custody_fields() -> None:
    guard = _guard()
    payload = _xrp_payment()
    payload["private_key"] = "deadbeef"
    with pytest.raises(GuardForbiddenSurfaceError):
        guard.bind_transaction(payload)


def test_bind_requires_sequence_or_ticket() -> None:
    with pytest.raises(GuardValidationError, match="sequence or ticket"):
        XRPLTransactionCandidate.from_dict(
            _xrp_payment(sequence=None, ticket_sequence=None)
        )


def test_bind_ticket_sequence() -> None:
    cand = XRPLTransactionCandidate.from_dict(
        _xrp_payment(sequence=None, ticket_sequence=55)
    )
    assert cand.ticket_sequence == 55
    guard = _guard()
    binding = guard.bind_transaction(cand, ledger_epoch=_ledger_epoch())
    assert binding.ticket_sequence == 55


def test_bind_signer_list() -> None:
    guard = _guard()
    signers = SignerListBinding(
        signers=[
            {"Account": SIGNER_A, "SignerWeight": 1},
            {"Account": SIGNER_B, "SignerWeight": 1},
        ],
        signer_quorum=2,
    )
    binding = guard.bind_transaction(
        _xrp_payment(),
        ledger_epoch=_ledger_epoch(),
        signer_list=signers,
    )
    assert binding.signer_list.signer_quorum == 2
    assert len(binding.signer_list.signers) == 2
    assert binding.signer_list.list_digest


def test_unsupported_hooks_without_capability_blocks() -> None:
    guard = _guard()
    cand = _xrp_payment(
        hooks_capability_present=False,
        hooks_effects=[{"hook_hash": "ab" * 32, "effect": "emit"}],
    )
    binding = guard.bind_transaction(cand, ledger_epoch=_ledger_epoch())
    request = _request_for(guard, binding, "req:hooks")
    decision = guard.evaluate(
        binding,
        request=request,
        now=_NOW_OK,
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
    )
    assert decision.allowed is False
    assert any("hooks" in c for c in decision.reason_codes)


# ---------------------------------------------------------------------------
# Evaluate allow path
# ---------------------------------------------------------------------------


def test_evaluate_allows_clean_xrp_payment() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_xrp_payment(), ledger_epoch=_ledger_epoch())
    request = _request_for(guard, binding)
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert isinstance(decision, XRPLGuardDecision)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.allowed is True
    assert decision.preflight is not None
    assert decision.preflight.capability is not None
    assert decision.binding_digest == binding.binding_digest


def test_evaluate_allows_issued_and_partial_with_delivered() -> None:
    guard = _guard()
    binding = guard.bind_transaction(
        _partial_payment(), ledger_epoch=_ledger_epoch()
    )
    assert binding.effects[0].delivered_amount_value == "1000000"
    request = _request_for(guard, binding, "req:partial-ok")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert decision.allowed is True

    issued_binding = guard.bind_transaction(
        _issued_payment(), ledger_epoch=_ledger_epoch()
    )
    assert issued_binding.effects[0].issuer == ISSUER
    request2 = _request_for(guard, issued_binding, "req:issued-ok")
    decision2 = guard.evaluate(
        issued_binding,
        request=request2,
        security_results={req: "pass" for req in request2.security_requirement_ids},
        compliance_results={req: "pass" for req in request2.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert decision2.allowed is True


def test_evaluate_stale_compliance_blocks() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_xrp_payment(), ledger_epoch=_ledger_epoch())
    request = _request_for(guard, binding, "req:stale-comp")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={
            req: "stale" for req in request.compliance_requirement_ids
        },
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert decision.blocks_automation is True
    assert decision.allowed is False


def test_evaluate_stale_ledger_blocks() -> None:
    guard = _guard(ledger_is_fresh=lambda _epoch, _now: False)
    binding = guard.bind_transaction(_xrp_payment(), ledger_epoch=_ledger_epoch())
    request = _request_for(guard, binding, "req:stale-ledger")
    decision = guard.evaluate(
        binding,
        request=request,
        now=_NOW_OK,
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
    )
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert any("ledger" in c or "stale" in c for c in decision.reason_codes)
    assert decision.blocks_automation is True


# ---------------------------------------------------------------------------
# Adversarial: mutation at consumption
# ---------------------------------------------------------------------------


def test_destination_tag_mutation_at_consumption() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_xrp_payment(), ledger_epoch=_ledger_epoch())
    request = _request_for(guard, binding, "req:tag-mut")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]

    live_tx = {
        "Account": ALICE,
        "Destination": BOB,
        "DestinationTag": 999,  # mutated from bound tag 42
        "TransactionType": "Payment",
        "Amount": "1000000",
        "Fee": "12",
        "Sequence": 7,
        "Flags": 0,
    }
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_ledger_epoch=_ledger_epoch(),
            live_tx=live_tx,
        )
    assert "tag" in str(excinfo.value).lower() or "tag" in excinfo.value.reason_code


def test_issuer_amount_mutation_at_consumption() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_issued_payment(), ledger_epoch=_ledger_epoch())
    request = _request_for(guard, binding, "req:issuer-mut")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]
    live_tx = {
        "Account": ALICE,
        "Destination": BOB,
        "DestinationTag": 99,
        "TransactionType": "Payment",
        "Amount": {"currency": "USD", "issuer": ISSUER, "value": "999"},  # mutated
        "Fee": "12",
        "Sequence": 7,
        "Flags": 0,
    }
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_ledger_epoch=_ledger_epoch(),
            live_tx=live_tx,
        )
    assert "amount" in excinfo.value.reason_code or "amount" in str(excinfo.value).lower()


def test_signer_list_mutation_at_consumption() -> None:
    guard = _guard()
    signers = SignerListBinding(
        signers=[
            {"Account": SIGNER_A, "SignerWeight": 1},
            {"Account": SIGNER_B, "SignerWeight": 1},
        ],
        signer_quorum=2,
    )
    binding = guard.bind_transaction(
        _xrp_payment(),
        ledger_epoch=_ledger_epoch(),
        signer_list=signers,
    )
    request = _request_for(guard, binding, "req:signer-mut")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]
    mutated = SignerListBinding(
        signers=[{"Account": SIGNER_A, "SignerWeight": 2}],  # list mutated
        signer_quorum=1,
    )
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
            live_ledger_epoch=_ledger_epoch(),
            live_signer_list=mutated,
        )
    assert "signer" in excinfo.value.reason_code


def test_ledger_epoch_mismatch_at_consumption() -> None:
    guard = _guard()
    epoch = _ledger_epoch()
    binding = guard.bind_transaction(_xrp_payment(), ledger_epoch=epoch)
    request = _request_for(guard, binding, "req:ledger-epoch")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_ledger_epoch=epoch,
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    mutated_epoch = _ledger_epoch(
        ledger_hash="BBBB000000000000000000000000000000000000000000000000000000000002"
    )
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_ledger_epoch=mutated_epoch,
        )
    assert "ledger" in excinfo.value.reason_code or "ledger" in str(excinfo.value).lower()


def test_evaluate_convenience_wrapper() -> None:
    decision = evaluate_xrpl_transaction_guard(
        _xrp_payment(),
        ledger_epoch=_ledger_epoch(),
        now=_NOW_OK,
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
    )
    assert isinstance(decision, XRPLGuardDecision)
    assert decision.allowed is True


def test_binary_float_amount_rejected() -> None:
    with pytest.raises(GuardValidationError):
        XRPLTransactionCandidate.from_dict(
            _xrp_payment(amount={"currency": "USD", "issuer": ISSUER, "value": 1.5})
        )


def test_normalized_effect_roundtrip() -> None:
    effect = NormalizedXRPLEffect(
        kind="payment",
        account=ALICE,
        destination=BOB,
        destination_tag=7,
        amount_kind="xrp",
        amount_value="100",
        fee_drops="12",
        sequence=1,
        flags=0,
        transaction_type="Payment",
    )
    restored = NormalizedXRPLEffect.from_dict(effect.to_dict())
    assert restored.destination_tag == 7
    assert restored.amount_value == "100"
