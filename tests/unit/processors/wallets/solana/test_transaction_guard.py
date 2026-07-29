"""Unit tests for the Solana transaction guard (CRYPTOIR-G540 / CRYPTOIR-031).

Offline adversarial fixtures cover:

* Message version, account order, address-table epoch, signer/writable bits,
  recent blockhash, program/program-data epoch, CPI/token effects, exact bytes.
* Substituted accounts/programs, privilege escalation, hidden CPI transfers,
  upgrades, stale blockhash, and stale compliance evidence.
* Re-resolution of address tables and executable program epochs at consumption.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.adapters.solana import (
    SOLANA_MAINNET_CHAIN_ID,
    SOLANA_MAINNET_GENESIS_HASH,
    SOLANA_MAINNET_NETWORK,
    SYSTEM_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    SolanaMessageCandidate,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.guard import (
    GuardCapabilityError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
    PreflightPhase,
)
from ipfs_datasets_py.processors.wallets.solana.transaction_guard import (
    SOLANA_TRANSACTION_GUARD_INTERFACE,
    AddressTableEpoch,
    ExecutableProgramEpoch,
    SolanaGuardDecision,
    SolanaMessageBinding,
    SolanaTransactionGuard,
    evaluate_solana_transaction_guard,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "wallets"
    / "solana"
    / "rpc_session.json"
)

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_LATE = "2026-07-28T12:20:00Z"


@pytest.fixture(scope="module")
def rpc_session() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _addrs(rpc: dict[str, Any]) -> dict[str, str]:
    return rpc["addresses"]


def _legacy_message(rpc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    addrs = _addrs(rpc)
    payload: dict[str, Any] = {
        "kind": "message_candidate",
        "intent_id": "intent:solana-legacy-1",
        "chain_id": SOLANA_MAINNET_CHAIN_ID,
        "network": SOLANA_MAINNET_NETWORK,
        "genesis_hash": SOLANA_MAINNET_GENESIS_HASH,
        "version": "legacy",
        "recent_blockhash": rpc["blocks"]["99"]["blockhash"],
        "fee_payer": addrs["alice"],
        "message": {
            "header": {
                "numRequiredSignatures": 1,
                "numReadonlySignedAccounts": 0,
                "numReadonlyUnsignedAccounts": 1,
            },
            "accountKeys": [
                addrs["alice"],
                addrs["bob"],
                SYSTEM_PROGRAM_ID,
            ],
            "recentBlockhash": rpc["blocks"]["99"]["blockhash"],
            "instructions": [
                {
                    "programId": SYSTEM_PROGRAM_ID,
                    "accounts": [0, 1],
                    "data": "3Bxs4NN",
                    "parsed": {
                        "type": "transfer",
                        "info": {
                            "source": addrs["alice"],
                            "destination": addrs["bob"],
                            "lamports": 1000,
                        },
                    },
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def _versioned_message(rpc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    addrs = _addrs(rpc)
    payload: dict[str, Any] = {
        "kind": "message_candidate",
        "intent_id": "intent:solana-v0-1",
        "chain_id": SOLANA_MAINNET_CHAIN_ID,
        "network": SOLANA_MAINNET_NETWORK,
        "genesis_hash": SOLANA_MAINNET_GENESIS_HASH,
        "version": "0",
        "recent_blockhash": rpc["blocks"]["99"]["blockhash"],
        "fee_payer": addrs["alice"],
        "message": {
            "header": {
                "numRequiredSignatures": 1,
                "numReadonlySignedAccounts": 0,
                "numReadonlyUnsignedAccounts": 1,
            },
            "accountKeys": [
                addrs["alice"],
                SYSTEM_PROGRAM_ID,
            ],
            "recentBlockhash": rpc["blocks"]["99"]["blockhash"],
            "instructions": [
                {
                    "programIdIndex": 1,
                    "accounts": [0, 2],
                    "data": "3Bxs4NN",
                }
            ],
            "addressTableLookups": [
                {
                    "accountKey": addrs["lookup_table"],
                    "writableIndexes": [0],
                    "readonlyIndexes": [],
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def _loaded_for_versioned(rpc: dict[str, Any]) -> dict[str, Any]:
    addrs = _addrs(rpc)
    return {"writable": [addrs["bob"]], "readonly": []}


def _program_epoch(program_id: str, **overrides: Any) -> ExecutableProgramEpoch:
    base = {
        "program_id": program_id,
        "code_epoch": f"epoch:{program_id[:12]}",
        "binary_digest": "a" * 64,
        "deployment_slot": 42,
        "chain_id": SOLANA_MAINNET_CHAIN_ID,
    }
    base.update(overrides)
    return ExecutableProgramEpoch(**base)


def _guard(**kwargs: Any) -> SolanaTransactionGuard:
    return SolanaTransactionGuard(**kwargs)


# ---------------------------------------------------------------------------
# AST / import surface
# ---------------------------------------------------------------------------


def test_ast_symbols_exported() -> None:
    from ipfs_datasets_py.processors.wallets.solana import transaction_guard as mod

    assert hasattr(mod, "SolanaTransactionGuard")
    assert hasattr(mod, "SolanaMessageCandidate")
    assert callable(mod.SolanaTransactionGuard)
    assert callable(mod.SolanaMessageCandidate)


def test_interface_constants() -> None:
    guard = _guard()
    assert guard.interface == SOLANA_TRANSACTION_GUARD_INTERFACE
    assert "solana" in guard.schema_version


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def test_bind_legacy_message_binds_all_fields(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    candidate = SolanaMessageCandidate.from_dict(_legacy_message(rpc_session))
    binding = guard.bind_message(candidate)

    assert isinstance(binding, SolanaMessageBinding)
    assert binding.message_version == "legacy"
    assert binding.recent_blockhash == rpc_session["blocks"]["99"]["blockhash"]
    assert binding.fee_payer == rpc_session["addresses"]["alice"]
    assert list(binding.account_order) == [
        rpc_session["addresses"]["alice"],
        rpc_session["addresses"]["bob"],
        SYSTEM_PROGRAM_ID,
    ]
    assert binding.privileges[0].is_signer is True
    assert binding.privileges[0].is_writable is True
    assert binding.privileges[1].is_signer is False
    assert binding.privileges[1].is_writable is True
    assert binding.privileges[2].is_writable is False
    assert binding.lamport_effects
    assert binding.lamport_effects[0]["lamports"] == "1000"
    assert binding.message_digest
    assert binding.serialized_digest
    assert binding.binding_digest
    assert binding.byte_length > 0


def test_bind_versioned_requires_loaded_addresses(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    with pytest.raises(GuardValidationError, match="addressTableLookups"):
        guard.bind_message(_versioned_message(rpc_session))


def test_bind_versioned_with_loaded_addresses(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_message(
        _versioned_message(rpc_session),
        loaded_addresses=_loaded_for_versioned(rpc_session),
    )
    assert binding.message_version in {"0", "v0"}
    assert len(binding.address_table_epochs) == 1
    table = binding.address_table_epochs[0]
    assert table.account_key == rpc_session["addresses"]["lookup_table"]
    assert table.writable_addresses == (rpc_session["addresses"]["bob"],)
    assert table.table_epoch
    # Account order: static then loaded writable.
    assert rpc_session["addresses"]["bob"] in binding.account_order


def test_bind_rejects_forbidden_custody_fields(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    payload = _legacy_message(rpc_session)
    payload["private_key"] = "deadbeef"
    with pytest.raises(GuardForbiddenSurfaceError):
        guard.bind_message(payload)


def test_bind_missing_blockhash_fails(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    payload = _legacy_message(rpc_session)
    payload["recent_blockhash"] = ""
    payload["message"] = dict(payload["message"])
    payload["message"]["recentBlockhash"] = ""
    with pytest.raises(GuardValidationError, match="recent_blockhash"):
        guard.bind_message(payload)


def test_bind_program_epochs_required_when_supplied(
    rpc_session: dict[str, Any],
) -> None:
    """When any program_epochs are supplied, every non-well-known program is required."""

    guard = _guard()
    addrs = _addrs(rpc_session)
    # Use a custom program id as the only instruction target.
    custom_program = addrs["mint"]  # valid 32-byte pubkey from fixture
    payload = _legacy_message(rpc_session)
    payload["message"] = dict(payload["message"])
    payload["message"]["accountKeys"] = [
        addrs["alice"],
        addrs["bob"],
        custom_program,
    ]
    payload["message"]["instructions"] = [
        {
            "programId": custom_program,
            "accounts": [0, 1],
            "data": "dead",
        }
    ]
    with pytest.raises(GuardValidationError, match="missing executable program epoch"):
        # Empty epoch set while a non-well-known program is invoked.
        guard.bind_message(payload, program_epochs=[])


def test_bind_program_epochs_match(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    addrs = _addrs(rpc_session)
    custom_program = addrs["mint"]
    payload = _legacy_message(rpc_session)
    payload["message"] = dict(payload["message"])
    payload["message"]["accountKeys"] = [
        addrs["alice"],
        addrs["bob"],
        custom_program,
    ]
    payload["message"]["instructions"] = [
        {"programId": custom_program, "accounts": [0, 1], "data": "ab"}
    ]
    epoch = _program_epoch(custom_program)
    binding = guard.bind_message(payload, program_epochs=[epoch])
    assert len(binding.program_epochs) == 1
    assert binding.program_epochs[0].code_epoch == epoch.code_epoch


# ---------------------------------------------------------------------------
# Evaluate allow path
# ---------------------------------------------------------------------------


def test_evaluate_allows_clean_legacy(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_message(_legacy_message(rpc_session))
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-1",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert isinstance(decision, SolanaGuardDecision)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.allowed is True
    assert decision.preflight is not None
    assert decision.preflight.capability is not None
    assert decision.binding_digest == binding.binding_digest


def test_evaluate_stale_compliance_blocks(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_message(_legacy_message(rpc_session))
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-stale-comp",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
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


def test_evaluate_stale_blockhash_blocks(rpc_session: dict[str, Any]) -> None:
    guard = _guard(blockhash_is_fresh=lambda _bh, _now: False)
    binding = guard.bind_message(_legacy_message(rpc_session))
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-stale-bh",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        now=_NOW_OK,
        compliance_results={
            req: "pass" for req in request.compliance_requirement_ids
        },
    )
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert any("blockhash" in c for c in decision.reason_codes)
    assert decision.blocks_automation is True


# ---------------------------------------------------------------------------
# Adversarial: substitution / privilege / hidden CPI / upgrade
# ---------------------------------------------------------------------------


def test_privilege_escalation_at_consumption(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_message(_legacy_message(rpc_session))
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-priv",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    assert capability is not None

    # Live message escalates bob to signer.
    live_msg = deepcopy(_legacy_message(rpc_session)["message"])
    live_msg["header"] = {
        "numRequiredSignatures": 2,
        "numReadonlySignedAccounts": 0,
        "numReadonlyUnsignedAccounts": 1,
    }
    with pytest.raises(GuardCapabilityError, match="privilege"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_message=live_msg,
        )


def test_account_order_substitution_at_consumption(
    rpc_session: dict[str, Any],
) -> None:
    guard = _guard()
    binding = guard.bind_message(_legacy_message(rpc_session))
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-order",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]

    live_msg = deepcopy(_legacy_message(rpc_session)["message"])
    # Swap alice and bob — account order is semantic.
    live_msg["accountKeys"] = [
        rpc_session["addresses"]["bob"],
        rpc_session["addresses"]["alice"],
        SYSTEM_PROGRAM_ID,
    ]
    with pytest.raises(GuardCapabilityError, match="account order"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_message=live_msg,
        )


def test_program_upgrade_blocks_consumption(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    addrs = _addrs(rpc_session)
    custom = addrs["mint"]
    payload = _legacy_message(rpc_session)
    payload["message"] = dict(payload["message"])
    payload["message"]["accountKeys"] = [addrs["alice"], addrs["bob"], custom]
    payload["message"]["instructions"] = [
        {"programId": custom, "accounts": [0, 1], "data": "ab"}
    ]
    epoch = _program_epoch(custom, code_epoch="code:v1", binary_digest="b" * 64)
    binding = guard.bind_message(payload, program_epochs=[epoch])
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-upgrade",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_program_epochs={custom: epoch},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]

    upgraded = _program_epoch(
        custom, code_epoch="code:v2-upgraded", binary_digest="c" * 64
    )
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
            live_program_epochs={custom: upgraded},
        )
    assert "upgrade" in str(excinfo.value).lower() or "program" in excinfo.value.reason_code


def test_address_table_epoch_mismatch_at_consumption(
    rpc_session: dict[str, Any],
) -> None:
    guard = _guard()
    loaded = _loaded_for_versioned(rpc_session)
    binding = guard.bind_message(
        _versioned_message(rpc_session),
        loaded_addresses=loaded,
    )
    assert binding.address_table_epochs
    original = binding.address_table_epochs[0]
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-alt",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_address_tables={original.account_key: original},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]

    # Substitute resolved writable address (hidden account swap via ALT).
    mutated = AddressTableEpoch(
        account_key=original.account_key,
        writable_indexes=original.writable_indexes,
        readonly_indexes=original.readonly_indexes,
        writable_addresses=(rpc_session["addresses"]["alice"],),  # substituted
        readonly_addresses=original.readonly_addresses,
        last_extended_slot=999,
    )
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_address_tables={original.account_key: mutated},
        )
    assert (
        "address table" in str(excinfo.value).lower()
        or "address_table" in excinfo.value.reason_code
    )


def test_hidden_cpi_blocks_evaluation(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    addrs = _addrs(rpc_session)
    payload = _legacy_message(rpc_session)
    # Craft binding with an inner instruction but no cpi_effects.
    binding = guard.bind_message(payload)
    # Manually inject an inner instruction into a rebuilt binding.
    from ipfs_datasets_py.logic.crypto_ir.adapters.solana import SolanaInstruction

    inner = SolanaInstruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=(addrs["alice"], addrs["bob"]),
        data="hidden",
        outer_index=0,
        inner_index=0,
        parsed_type="transfer",
        parsed_info={
            "source": addrs["alice"],
            "destination": addrs["bob"],
            "amount": "99",
        },
    )
    data = binding.to_dict()
    data["instructions"] = [i.to_dict() for i in binding.instructions] + [
        inner.to_dict()
    ]
    data["cpi_effects"] = []  # deliberately empty → hidden CPI
    data["binding_digest"] = ""  # recompute
    adversarial = SolanaMessageBinding.from_dict(data)

    request = guard.to_preflight_request(
        adversarial,
        request_id="req:solana-hidden-cpi",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        adversarial,
        request=request,
        now=_NOW_OK,
        compliance_results={
            req: "pass" for req in request.compliance_requirement_ids
        },
    )
    assert decision.allowed is False
    assert decision.blocks_automation is True
    assert any("cpi" in c for c in decision.reason_codes) or any(
        "cpi" in r.lower() for r in decision.reasons
    )


# ---------------------------------------------------------------------------
# Happy-path consumption with re-resolve
# ---------------------------------------------------------------------------


def test_consumption_re_resolves_matching_epochs(
    rpc_session: dict[str, Any],
) -> None:
    guard = _guard()
    addrs = _addrs(rpc_session)
    custom = addrs["mint"]
    payload = _legacy_message(rpc_session)
    payload["message"] = dict(payload["message"])
    payload["message"]["accountKeys"] = [addrs["alice"], addrs["bob"], custom]
    payload["message"]["instructions"] = [
        {"programId": custom, "accounts": [0, 1], "data": "ab"}
    ]
    epoch = _program_epoch(custom)
    binding = guard.bind_message(payload, program_epochs=[epoch])
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-consume-ok",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_program_epochs={custom: epoch},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]

    result = guard.revalidate_and_consume(
        capability,
        request,
        binding,
        phase=PreflightPhase.PRE_SIGN,
        now=_NOW_OK,
        live_program_epochs={custom: epoch},
        live_message=payload["message"],
    )
    assert result.allowed is True
    assert result.phase == PreflightPhase.PRE_SIGN.value

    # Second consumption races / fails closed.
    with pytest.raises(Exception):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
            live_program_epochs={custom: epoch},
        )


def test_unresolved_program_epoch_at_consumption_blocks(
    rpc_session: dict[str, Any],
) -> None:
    guard = _guard()
    addrs = _addrs(rpc_session)
    custom = addrs["mint"]
    payload = _legacy_message(rpc_session)
    payload["message"] = dict(payload["message"])
    payload["message"]["accountKeys"] = [addrs["alice"], addrs["bob"], custom]
    payload["message"]["instructions"] = [
        {"programId": custom, "accounts": [0, 1], "data": "ab"}
    ]
    epoch = _program_epoch(custom)
    binding = guard.bind_message(payload, program_epochs=[epoch])
    request = guard.to_preflight_request(
        binding,
        request_id="req:solana-unresolved",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_program_epochs={custom: epoch},
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]

    # Empty live map → cannot re-resolve non-synthetic program epoch.
    with pytest.raises(GuardCapabilityError, match="re-resolved|unresolved|program"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_program_epochs={},
        )


# ---------------------------------------------------------------------------
# Convenience + serialization
# ---------------------------------------------------------------------------


def test_evaluate_solana_transaction_guard_helper(
    rpc_session: dict[str, Any],
) -> None:
    decision = evaluate_solana_transaction_guard(
        _legacy_message(rpc_session),
        request_id="req:helper",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        now=_NOW_OK,
        security_results={
            req: "pass"
            for req in (
                "sec:solana-message-binding",
                "sec:solana-account-privileges",
                "sec:solana-address-table-epoch",
                "sec:solana-program-epoch",
                "sec:solana-blockhash-freshness",
                "sec:solana-cpi-effects",
            )
        },
        compliance_results={
            "comp:direct-sanctions": "pass",
            "comp:bounded-exposure": "pass",
        },
    )
    assert decision.outcome is TransactionVerdictOutcome.ALLOW


def test_binding_round_trip(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_message(_legacy_message(rpc_session))
    restored = SolanaMessageBinding.from_dict(binding.to_dict())
    assert restored.binding_digest == binding.binding_digest
    assert restored.account_order == binding.account_order
    assert restored.message_version == binding.message_version


def test_address_table_epoch_digest_stable(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    a = AddressTableEpoch(
        account_key=addrs["lookup_table"],
        writable_indexes=(0,),
        writable_addresses=(addrs["bob"],),
    )
    b = AddressTableEpoch(
        account_key=addrs["lookup_table"],
        writable_indexes=(0,),
        writable_addresses=(addrs["bob"],),
    )
    assert a.table_epoch == b.table_epoch
    c = AddressTableEpoch(
        account_key=addrs["lookup_table"],
        writable_indexes=(0,),
        writable_addresses=(addrs["alice"],),
    )
    assert c.table_epoch != a.table_epoch


def test_no_signing_or_broadcast_surface() -> None:
    """Guard public surface must not expose custody APIs."""

    from ipfs_datasets_py.processors.wallets.solana import transaction_guard as mod

    forbidden = {
        "sign",
        "sign_transaction",
        "broadcast",
        "send_transaction",
        "private_key",
    }
    public = {name for name in dir(mod) if not name.startswith("_")}
    assert not (public & forbidden)
    methods = {
        name
        for name in dir(SolanaTransactionGuard)
        if not name.startswith("_")
    }
    assert not (methods & forbidden)
