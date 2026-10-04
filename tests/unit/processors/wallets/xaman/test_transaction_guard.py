"""Unit tests for the Xaman transaction guard (CRYPTOIR-G550 / CRYPTOIR-029).

Offline adversarial fixtures cover:

* Shared XRPL effects (destination/tag, issuer, partial payment, sequence,
  fee, signer list, ledger epoch) plus Xaman payload identity.
* Xaman approval workflow evidence does **not** replace transaction policy
  authorization.
* Tag/issuer/amount/signature-list mutation, unsupported Hooks, stale ledger,
  and compliance changes block.
"""

from __future__ import annotations

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
    PreflightPhase,
)
from ipfs_datasets_py.processors.wallets.xaman.transaction_guard import (
    APPROVAL_CANNOT_REPLACE,
    XAMAN_TRANSACTION_GUARD_INTERFACE,
    XamanGuardDecision,
    XamanPayloadIdentity,
    XamanTransactionBinding,
    XamanTransactionGuard,
    XRPLTransactionCandidate,
    evaluate_xaman_transaction_guard,
)
from ipfs_datasets_py.processors.wallets.xrpl.transaction_guard import (
    LedgerEpoch,
    SignerListBinding,
)

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"

ALICE = "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz"
BOB = "rUFiTVw3LSgEqrHV7yPL4nZ1n6f6QgjjfU"
ISSUER = "r3bmF74WayREhyVYaqbu7GqLKvqZvUF3k6"

PAYLOAD_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
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
        "intent_id": "intent:xaman-payment-1",
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


def _payload(**overrides: Any) -> XamanPayloadIdentity:
    base = {
        "payload_id": PAYLOAD_UUID,
        "application_id": "app:demo",
        "application_name": "Demo App",
        "payload_type": "transaction",
        "network_type": "mainnet",
        "workflow_observation": {
            "payload_status": "opened",
            "obs:device": "ios",
        },
    }
    base.update(overrides)
    return XamanPayloadIdentity(**base)


def _guard(**kwargs: Any) -> XamanTransactionGuard:
    return XamanTransactionGuard(**kwargs)


def _request_for(
    guard: XamanTransactionGuard,
    binding: XamanTransactionBinding,
    request_id: str = "req:xaman-1",
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
    from ipfs_datasets_py.processors.wallets.xaman import transaction_guard as mod

    assert hasattr(mod, "XamanTransactionGuard")
    assert hasattr(mod, "XRPLTransactionCandidate")
    assert callable(mod.XamanTransactionGuard)
    assert callable(mod.XRPLTransactionCandidate)


def test_interface_constants() -> None:
    guard = _guard()
    assert guard.interface == XAMAN_TRANSACTION_GUARD_INTERFACE
    assert "xaman" in guard.schema_version


def test_approval_cannot_replace_policy_boundary() -> None:
    assert "transaction_policy_authorization" in APPROVAL_CANNOT_REPLACE
    assert "sanctions_policy" in APPROVAL_CANNOT_REPLACE
    assert "admissibility_capability" in APPROVAL_CANNOT_REPLACE


# ---------------------------------------------------------------------------
# Payload identity + binding
# ---------------------------------------------------------------------------


def test_payload_identity_binds_uuid() -> None:
    payload = _payload()
    assert payload.payload_id == PAYLOAD_UUID
    assert payload.identity_digest
    assert payload.workflow_observation.to_dict().get("payload_status") == "opened"


def test_bind_payload_shares_xrpl_effects() -> None:
    guard = _guard()
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(),
        ledger_epoch=_ledger_epoch(),
    )
    assert isinstance(binding, XamanTransactionBinding)
    assert binding.payload.payload_id == PAYLOAD_UUID
    assert binding.xrpl_binding.destination == BOB
    assert binding.xrpl_binding.destination_tag == 42
    assert binding.effects[0].amount_value == "1000000"
    assert binding.binding_digest
    assert binding.binding_digest != binding.xrpl_binding.binding_digest


def test_bind_rejects_approval_authority_fields_on_candidate() -> None:
    guard = _guard()
    cand = _xrp_payment()
    cand["user_approved"] = True
    with pytest.raises(GuardForbiddenSurfaceError) as excinfo:
        guard.bind_payload(cand, _payload(), ledger_epoch=_ledger_epoch())
    assert "approval" in str(excinfo.value).lower() or "user_approved" in str(
        excinfo.value
    )


def test_bind_rejects_approval_fields_on_payload() -> None:
    guard = _guard()
    with pytest.raises(GuardForbiddenSurfaceError):
        guard.bind_payload(
            _xrp_payment(),
            {
                "payload_id": PAYLOAD_UUID,
                "user_approved": True,
            },
            ledger_epoch=_ledger_epoch(),
        )


def test_bind_rejects_signed_workflow_authority() -> None:
    guard = _guard()
    with pytest.raises(GuardForbiddenSurfaceError):
        guard.bind_payload(
            _xrp_payment(),
            {
                "payload_id": PAYLOAD_UUID,
                "signed": True,
                "resolved": True,
            },
            ledger_epoch=_ledger_epoch(),
        )


# ---------------------------------------------------------------------------
# Evaluate allow path + approval non-authority
# ---------------------------------------------------------------------------


def test_evaluate_allows_with_payload_identity() -> None:
    guard = _guard()
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(),
        ledger_epoch=_ledger_epoch(),
    )
    request = _request_for(guard, binding)
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert isinstance(decision, XamanGuardDecision)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.allowed is True
    assert decision.preflight is not None
    assert decision.preflight.capability is not None
    assert decision.binding_digest == binding.binding_digest
    assert decision.attributes.to_dict().get("payload_id") == PAYLOAD_UUID
    assert "transaction_policy_authorization" in decision.attributes.to_dict().get(
        "approval_cannot_replace", []
    )


def test_evaluate_rejects_approval_kwargs_as_authority() -> None:
    """Xaman user-approved flags must not be accepted as evaluation authority."""

    guard = _guard()
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(),
        ledger_epoch=_ledger_epoch(),
    )
    with pytest.raises(GuardForbiddenSurfaceError) as excinfo:
        guard.evaluate(
            binding,
            now=_NOW_OK,
            xaman_user_approved=True,
            xaman_workflow_resolved=True,
        )
    assert "does not replace" in str(excinfo.value).lower() or "approval" in str(
        excinfo.value
    ).lower()


def test_evaluate_stale_compliance_blocks_even_if_payload_opened() -> None:
    guard = _guard()
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(
            workflow_observation={"payload_status": "opened", "obs:note": "user-seen"}
        ),
        ledger_epoch=_ledger_epoch(),
    )
    request = _request_for(guard, binding, "req:xaman-stale")
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


def test_partial_payment_and_issued_share_xrpl_path() -> None:
    guard = _guard()
    partial = _xrp_payment(
        intent_id="intent:xaman-partial",
        flags=TF_PARTIAL_PAYMENT,
        amount="5000000",
        delivered_amount="1000000",
        meta={"delivered_amount": "1000000"},
    )
    binding = guard.bind_payload(partial, _payload(), ledger_epoch=_ledger_epoch())
    assert binding.effects[0].partial_payment is True
    assert binding.effects[0].delivered_amount_value == "1000000"
    request = _request_for(guard, binding, "req:xaman-partial")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert decision.allowed is True

    issued = _xrp_payment(
        intent_id="intent:xaman-issued",
        amount={"currency": "USD", "issuer": ISSUER, "value": "10"},
    )
    binding2 = guard.bind_payload(
        issued,
        XamanPayloadIdentity(payload_id="payload:issued-1"),
        ledger_epoch=_ledger_epoch(),
    )
    assert binding2.effects[0].issuer == ISSUER


def test_unsupported_hooks_block_xaman_path() -> None:
    guard = _guard()
    cand = _xrp_payment(
        hooks_capability_present=False,
        hooks_effects=[{"hook_hash": "cd" * 32}],
    )
    binding = guard.bind_payload(cand, _payload(), ledger_epoch=_ledger_epoch())
    request = _request_for(guard, binding, "req:xaman-hooks")
    decision = guard.evaluate(
        binding,
        request=request,
        now=_NOW_OK,
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
    )
    assert decision.allowed is False
    assert any("hooks" in c for c in decision.reason_codes)


# ---------------------------------------------------------------------------
# Consumption mutations
# ---------------------------------------------------------------------------


def test_payload_id_substitution_at_consumption() -> None:
    guard = _guard()
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(),
        ledger_epoch=_ledger_epoch(),
    )
    request = _request_for(guard, binding, "req:xaman-payload-sub")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_ledger_epoch=_ledger_epoch(),
            live_payload_id="00000000-0000-0000-0000-000000000099",
        )
    assert "payload" in excinfo.value.reason_code


def test_destination_tag_mutation_on_xaman_path() -> None:
    guard = _guard()
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(),
        ledger_epoch=_ledger_epoch(),
    )
    request = _request_for(guard, binding, "req:xaman-tag")
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
        "DestinationTag": 777,
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
    assert "tag" in excinfo.value.reason_code or "tag" in str(excinfo.value).lower()


def test_signer_list_mutation_on_xaman_path() -> None:
    guard = _guard()
    signers = SignerListBinding(
        signers=[
            {"Account": ALICE, "SignerWeight": 1},
            {"Account": BOB, "SignerWeight": 1},
        ],
        signer_quorum=2,
    )
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(),
        ledger_epoch=_ledger_epoch(),
        signer_list=signers,
    )
    request = _request_for(guard, binding, "req:xaman-signers")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]
    mutated = SignerListBinding(
        signers=[{"Account": ALICE, "SignerWeight": 1}],
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


def test_stale_ledger_blocks_xaman_evaluate() -> None:
    from ipfs_datasets_py.processors.wallets.xrpl.transaction_guard import (
        XRPLTransactionGuard,
    )

    xrpl = XRPLTransactionGuard(ledger_is_fresh=lambda _e, _n: False)
    guard = XamanTransactionGuard(xrpl_guard=xrpl)
    binding = guard.bind_payload(
        _xrp_payment(),
        _payload(),
        ledger_epoch=_ledger_epoch(),
    )
    request = _request_for(guard, binding, "req:xaman-stale-ledger")
    decision = guard.evaluate(
        binding,
        request=request,
        now=_NOW_OK,
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
    )
    assert decision.blocks_automation is True
    assert decision.allowed is False


def test_evaluate_convenience_wrapper() -> None:
    decision = evaluate_xaman_transaction_guard(
        _xrp_payment(),
        PAYLOAD_UUID,
        ledger_epoch=_ledger_epoch(),
        now=_NOW_OK,
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
    )
    assert isinstance(decision, XamanGuardDecision)
    assert decision.allowed is True


def test_candidate_from_dict_on_xaman_import() -> None:
    cand = XRPLTransactionCandidate.from_dict(_xrp_payment())
    assert cand.account == ALICE
    assert cand.destination_tag == 42
